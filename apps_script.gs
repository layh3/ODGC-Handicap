/**
 * ODGC Handicap — Google Sheets Apps Script backend.
 *
 * This script lives inside the master Google Sheet. It exposes a small POST
 * RPC that the Python scripts (import_udisc.py / import_pdga.py / hc24.py)
 * use to read and write rounds when they're run in --gsheet mode.
 *
 * The deployment URL acts as the write capability — anyone with the URL
 * can call these functions. Store it in `gsheets_url.txt` next to hc24.py
 * (which is gitignored).
 *
 * Actions (POST body is JSON):
 *   {"action": "ping"}
 *       Health check. Returns sheet dimensions so you can confirm the URL
 *       targets the right spreadsheet/tab.
 *
 *   {"action": "pull",  "sheet": "active2025"}
 *       Returns the entire tab as a 2D array under `data`.
 *
 *   {"action": "append_rows", "sheet": "active2025",
 *    "rows": [[26, "TOSS05", "alb", 0, 47, 0, ...], ...]}
 *       Appends N rows at the next free row. Each row's length must match
 *       the others. Used by importers to add new round rows.
 *
 *   {"action": "add_player", "sheet": "active2025",
 *    "name": "Arch_Jerry", "after_col": 234}
 *       Inserts a new column right of column `after_col`. Fills:
 *         row 1: name
 *         row 2: -1                (seed HC sentinel = "no seed")
 *         rows 3-9: 100             (seed-diff sentinels = "no data")
 *         rows 10-13: 0             (ODGC/Atos/EV/Ladies membership flags)
 *
 *   {"action": "replace_sheet", "target_sheet": "HC",
 *    "rows": [[...header...], [...row...], ...]}
 *       Deletes the named tab if it exists and creates a fresh one with the
 *       given 2D values. Used by hc24.py to push the recomputed handicap
 *       rankings into a tab in this spreadsheet.
 *
 * Setup (one time, takes ~5 minutes):
 *   1. Open the Sheet → Extensions → Apps Script.
 *   2. Paste this whole file into the editor (replace the default Code.gs).
 *   3. Save (cmd-S). It auto-detects the parent spreadsheet — no IDs to fill in.
 *   4. Deploy → New deployment → Type: Web app.
 *      - Description:  ODGC HC bot
 *      - Execute as:   Me
 *      - Who has access:  Anyone
 *      Click Deploy. Authorize when prompted (this is your own script
 *      asking to access your own sheet — you click through).
 *   5. Copy the deployment URL it gives you (looks like
 *      https://script.google.com/macros/s/AKfy.../exec).
 *   6. Paste that URL into gsheets_url.txt next to hc24.py.
 *
 * Re-deploying after changes: Deploy → Manage deployments → pencil edit →
 * Version: New version → Deploy. Keeps the same URL.
 */

function doPost(e) {
  let req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return jsonResponse({ok: false, error: 'invalid JSON body: ' + err});
  }

  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheetName = req.sheet || 'active2025';
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return jsonResponse({ok: false, error: 'sheet not found: ' + sheetName});
    }

    // Serialize writes; two concurrent imports could otherwise race on
    // append_rows / add_player.
    const lock = LockService.getDocumentLock();
    lock.waitLock(30000);
    try {
      switch (req.action) {

        case 'ping':
          return jsonResponse({
            ok: true,
            action: 'ping',
            spreadsheet: ss.getName(),
            sheet: sheetName,
            rows: sheet.getLastRow(),
            cols: sheet.getLastColumn(),
          });

        case 'pull': {
          const data = sheet.getDataRange().getValues();
          return jsonResponse({ok: true, data: data});
        }

        case 'append_rows': {
          const rows = req.rows;
          if (!rows || rows.length === 0) {
            return jsonResponse({ok: false, error: 'rows array is empty'});
          }
          const width = rows[0].length;
          for (let i = 0; i < rows.length; i++) {
            if (rows[i].length !== width) {
              return jsonResponse({
                ok: false,
                error: 'row ' + i + ' has width ' + rows[i].length +
                       ' but row 0 has width ' + width,
              });
            }
          }
          // Find the last row that has content in column A (the year column),
          // not just sheet.getLastRow() which counts any column's last filled
          // row — helper formulas like a count column in col Z would otherwise
          // push our append far below the round data, leaving a gap that
          // hc24.py's parser would treat as end-of-data.
          const lastRowAny = sheet.getLastRow();
          let startRow = 14;  // first round row, fallback if column A is empty
          if (lastRowAny > 0) {
            const colA = sheet.getRange(1, 1, lastRowAny, 1).getValues();
            for (let i = colA.length - 1; i >= 0; i--) {
              if (colA[i][0] !== '' && colA[i][0] !== null) {
                startRow = i + 2;  // 0-index → 1-index, then +1 to land on the row AFTER
                break;
              }
            }
          }
          sheet.getRange(startRow, 1, rows.length, width).setValues(rows);
          return jsonResponse({
            ok: true,
            rows_appended: rows.length,
            first_row: startRow,
            last_row: startRow + rows.length - 1,
          });
        }

        case 'add_player': {
          const name = req.name;
          const afterCol = req.after_col;
          if (!name) return jsonResponse({ok: false, error: 'name required'});
          if (!afterCol) return jsonResponse({ok: false, error: 'after_col required'});

          sheet.insertColumnAfter(afterCol);
          const newCol = afterCol + 1;
          const seedValues = [
            [name],   // row 1: player name
            [-1],     // row 2: seed HC sentinel
            [100], [100], [100], [100], [100], [100], [100],  // rows 3-9: seed diffs
            [0], [0], [0], [0],   // rows 10-13: ODGC, Atos, EV, Ladies flags
          ];
          sheet.getRange(1, newCol, seedValues.length, 1).setValues(seedValues);
          return jsonResponse({ok: true, name: name, col: newCol});
        }

        case 'set_membership': {
          // Toggle a player's club-membership flags (rows 10-13).
          // body: {sheet, name, flags: {ODGC?, TOSS?, EV?, Ladies?}}
          //   flag keys are optional — only those provided are written.
          const targetName = req.name;
          if (!targetName) return jsonResponse({ok: false, error: 'name required'});
          const flags = req.flags || {};
          const playerCol = findPlayerCol_(sheet, targetName);
          if (playerCol < 0) {
            return jsonResponse({ok: false, error: 'player not found: ' + targetName});
          }
          const rowMap = { ODGC: 10, TOSS: 11, EV: 12, Ladies: 13 };
          const applied = {};
          for (const key in rowMap) {
            if (Object.prototype.hasOwnProperty.call(flags, key)) {
              const v = flags[key] ? 1 : 0;
              sheet.getRange(rowMap[key], playerCol).setValue(v);
              applied[key] = v;
            }
          }
          return jsonResponse({ok: true, name: targetName, col: playerCol, applied: applied});
        }

        case 'rename_player': {
          // Change a player's name in row 1 (the roster header for their column).
          // body: {sheet, old_name, new_name}
          const oldN = req.old_name;
          const newN = req.new_name;
          if (!oldN || !newN) {
            return jsonResponse({ok: false, error: 'old_name and new_name required'});
          }
          const playerCol = findPlayerCol_(sheet, oldN);
          if (playerCol < 0) {
            return jsonResponse({ok: false, error: 'player not found: ' + oldN});
          }
          sheet.getRange(1, playerCol).setValue(newN);
          return jsonResponse({ok: true, old_name: oldN, new_name: newN, col: playerCol});
        }

        case 'replace_sheet': {
          // Drop and recreate `target_sheet` with the given 2D values.
          // Uses target_sheet (not sheet) so the caller can publish to a
          // different tab from the one they're reading from.
          //
          // Optional `freeze_rows` / `freeze_cols` lock those leading
          // rows/columns in place when the user scrolls.
          const targetName = req.target_sheet || 'HC';
          const rows = req.rows || [];
          let target = ss.getSheetByName(targetName);
          if (target) {
            if (ss.getSheets().length === 1) {
              return jsonResponse({
                ok: false,
                error: 'cannot replace the only sheet in the spreadsheet',
              });
            }
            ss.deleteSheet(target);
          }
          target = ss.insertSheet(targetName);
          if (rows.length > 0) {
            let width = 0;
            for (let i = 0; i < rows.length; i++) {
              if (rows[i].length > width) width = rows[i].length;
            }
            for (let i = 0; i < rows.length; i++) {
              while (rows[i].length < width) rows[i].push('');
            }
            target.getRange(1, 1, rows.length, width).setValues(rows);
          }
          if (req.freeze_rows && req.freeze_rows > 0) {
            target.setFrozenRows(req.freeze_rows);
          }
          if (req.freeze_cols && req.freeze_cols > 0) {
            target.setFrozenColumns(req.freeze_cols);
          }
          return jsonResponse({
            ok: true,
            target_sheet: targetName,
            rows: rows.length,
            frozen_rows: req.freeze_rows || 0,
            frozen_cols: req.freeze_cols || 0,
          });
        }

        default:
          return jsonResponse({ok: false, error: 'unknown action: ' + req.action});
      }
    } finally {
      lock.releaseLock();
    }
  } catch (err) {
    return jsonResponse({ok: false, error: err.toString()});
  }
}

// GET returns help text — useful for confirming the deployment URL is live.
function doGet(e) {
  return ContentService
    .createTextOutput(
      'ODGC HC Apps Script is live.\n\n' +
      'POST JSON to this URL with one of:\n' +
      '  {"action":"ping"}\n' +
      '  {"action":"pull","sheet":"active2025"}\n' +
      '  {"action":"append_rows","sheet":"active2025","rows":[[...],[...]]}\n' +
      '  {"action":"add_player","sheet":"active2025","name":"Foo_Bar","after_col":234}\n'
    )
    .setMimeType(ContentService.MimeType.TEXT);
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// Find a player's 1-indexed sheet column by exact name match in row 1.
// Roster starts at column D (4); stops scanning at the first blank cell
// or at one of the helper labels (count, total, …) that may follow.
function findPlayerCol_(sheet, name) {
  const lastCol = sheet.getLastColumn();
  if (lastCol < 4) return -1;
  const row1 = sheet.getRange(1, 4, 1, lastCol - 3).getValues()[0];
  const target = String(name).trim();
  const helpers = {count:1, total:1, sum:1, tally:1, n:1, '#':1};
  for (let i = 0; i < row1.length; i++) {
    const v = row1[i];
    if (v === '' || v === null) break;
    const s = String(v).trim();
    if (helpers[s.toLowerCase()]) break;
    if (s === target) return i + 4;
  }
  return -1;
}
