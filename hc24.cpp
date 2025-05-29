//  odgc HC algorith  kd Jan 2018
#include "stdafx.h"
// #include <stdev.h>
// reading a text file
#include <iostream> 
#include <iomanip>
#include <sstream>
#include <fstream>
#include <string>
#include <algorithm>
#include <array>
using namespace std;


ifstream myfile("RoundData.dat");   // input file, contains players' names, end-of-2014 HCs, round (course) info and round scores  (0 if player did not attend...)
// ifstream myfile("newRoundData.dat");   // input file, contains players' names, end-of-2014 HCs, round (course) info and round scores  (0 if player did not attend...)
ifstream winfile("TOSS_adj_winners2015-2017.dat");  //  input file, lists number of payouts per TOSS event and the names of adjusted scores cash winners
ofstream my2file("example.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream tossfile("odgcHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream odgccafile("odgccaCH.txt");  //  for odgc.ca website output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream Atosfile("atosHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream evfile("evHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream kvfile("kvHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream cmfile("ladiesHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data
ofstream my3file("debug.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data

// function routines, code in other external files 
//   stdev is a fn to calc standard deviation, LeastSquares does regression for round slope, hcCalc determines HCs based on array of differentials
#include "stdev.h"
#include "LeastSquares.h"
#include "hcCalc.h" 

int main() {
	//	std::cout << std::fixed;
	//	std::cout << std::setprecision(2);

		//  global variables declared and initialized for use in code
#include "initialize_variables.h"

	if (myfile.is_open())
	{
		getline(myfile, line);
		{

			istringstream iss(line);
			string word;

			while (iss >> word) {
				/* do stuff with word */

				player[i_pl] = word;   i_pl++;   //  read player name and index no. //    
				cout << i_pl - 1 << "  " << player[i_pl - 1] << '\n';
				//  std::cin.get();  this line halts execution for debugging...

			}
			i_pl--;   // corrects index number of players
		}
		my2file << " line 46 ok   player  " << player[i_pl] << "i_pl = " << i_pl << '\n';

		if (my2file.is_open())
			//  read the rounddata file
			// first, read in initial end of 2020 handicaps...

			string dummy0, dummy;  double dum;
		myfile >> dummy >> dummy; my2file << "2nd dummy HC ::    " << dummy << " " << i_pl << '\n';
		for (int j = 1; j <= i_pl; j++) {
			myfile >> hc[j];   // my2file << player[j] << " has hc of: " << hc[j] << '\n';
		}
		my2file << " line 57 ok   hc[114] =   " << hc[i_pl] << '\n';
		//  read 7 lines of differentials  //  reset reseed HCs
		for (int k = 1; k < 8; k++) {		//my2file << " line 59 ok   into loop  k  =   " << k << '\n'; 
			//	myfile >> dummy >> dummy; my2file << "2nd dummy HC diffs::    " << dummy << '\n';
			for (int j = 1; j <= i_pl; j++) {   // my2file << " line 61 ok   into loop  j  =   " << j << '\n'; 
				myfile >> dum;
				if (dum < 90.0) {
					rnd_count[j]++; diff[j][k] = dum; d_ry[j][k] = 20;
				}
			}
		}

		my2file << " line 67 ok   last diff" << diff[i_pl][3] << " hc[114] = " << hc[i_pl] << '\n';

		//  read ODGC member status array
		myfile >> dummy >> dummy; my2file << "  line72 2nd dummy EV ::    " << dummy << '\n';
		for (int j = 1; j <= i_pl; j++) {
			myfile >> ODGCmem_stat[j];
			// my2file << player[j] << " ODGCmember status: " << ODGCmem_stat[j] << '\n';;

		}//  read ATOS list member status array
		myfile >> dummy >> dummy; my2file << "  line72 2nd dummy EV ::    " << dummy << '\n';

		for (int j = 1; j <= i_pl; j++) {
			myfile >> TOSSmem_stat[j];
			// my2file << player[j] << " TOSSmember status: " << TOSSmem_stat[j] << '\n';;
		}
		//  read EV member status array
		myfile >> dummy >> dummy; my2file << "  line72 2nd dummy EV ::    " << dummy << '\n';
		for (int j = 1; j <= i_pl; j++) {
			myfile >> EVmem_stat[j];
			// my2file << player[j] << " EVmember status: " << EVmem_stat[j] << '\n';;
		}

		//  read LadiesLeague member status array
		myfile >> dummy >> dummy; my2file << "  line72 2nd dummy EV ::    " << dummy << '\n';
		 

		for (int j = 1; j <= i_pl; j++) {
			myfile >> LLmem_stat[j];
			// my2file << player[j] << " LLmember status: " << LLmem_stat[j] << '\n';;
		}

		//  first, set up historical arrays of course ref scores before adding news ones.
		//  this was done hardcode in initialize_variables.H

	//	myfile >> dummy0 >> dummy;  //  read dummy line of data file

									// read in round scores from roundData.dat file  
		my2file << " line 80 ok " << '\n';

		


		while (!myfile.eof())  // read round info & scores, line by line
		{
			i_rc++;  // my2file << " line 90 ok i_rc = " << i_rc << '\n';

			//myfile >> jin;  my2file << " line 92 test  jin  = " << jin << '\n';  exit(0);
			myfile >> ry[i_rc] >> event[i_rc] >> course[i_rc]; //  read info and course code
			//my2file << " line 92 ok i_rc = " << i_rc << " ry[i_rc] = " << ry[i_rc] << " event[i_rc] = " << event[i_rc] << " course[i_rc] = " << course[i_rc] << '\n';
		//	my2file << " line 92 ok i_rc = " << i_rc <<  " event[i_rc].length() = " << event[i_rc].length() << '\n';
			// 	cout << " line 92 ok i_rc = " << i_rc << " ry[i_rc] = " << ry[i_rc] << " event[i_rc] = " << event[i_rc] << " course[i_rc] = " << course[i_rc] << '\n';
			if (event[i_rc].length() < 3) break;  // exit, when nothing left to read
			for (int j = 1; j <= i_pl; j++) {
				myfile >> score[i_rc][j];    // read in all scores for round
			}

			// my2file << " line 96 ok i_rc = " << i_rc <<  "johnny's round total = " <<  rnd_count[94] << '\n';   

			//  note course played on::   catalog course id info  i_c is course ID index
			i_c = 0; for (int j = 1; j < num_crs; j++)if (course[i_rc] == courseID[j]) i_c = j;
			//		my2file << " TEST::: i_c = " << i_c << " 1st char  event[r][0]:: " << event[i_rc][0] << endl;
			if (event[i_rc][0] == 'x')i_c = 0;  //  course codes given x in first position for rounds which are B-tier, excluded from reference score for course (ie; lower divisions of plaid or OO)
			course_rnds[i_c]++;
			//	if (event[i_rc][0] == 'x') my2file << "  FILTERED::i_c = " << i_c << " 1st char  event[r][0]:: " << event[i_rc][0] << " course_rnds[i_c] = " << course_rnds[i_c] << endl;
			//  create irnd_scores from score data
			rnd_size = 0;
			for (int j = 1; j <= i_pl; j++) {  // if score read is 0, player not present, counts players, assigns scores to intra-round array
				if (score[i_rc][j] > 0) {
					rnd_size++;	irnd_scores[rnd_size] = score[i_rc][j];
				}
			}

			//my2file << " line 116 ok rnd_size = " << rnd_size << '\n';
			//  collect top 5 raw course reference scores, update course ref value for difficulty factor...
			if (i_c > 0) {

				sort(irnd_scores, irnd_scores + rnd_size + 1);
				//	my2file << "  after sort crs_ref::round  = " << i_rc << " i_c  = " << i_c << "  course = " << course[i_rc] << "  course_rnds[i_c] = " << course_rnds[i_c] << '\n';
			   //	for (int j = 1; j <= rnd_size; j++){ my2file << "  after sort crs_ref:: j  = " << j << "  irnd_scores[j]  = " << irnd_scores[j] << '\n';	}

				rnd_std = 0;  //  rnd_std is avg of top 5 raw scores, reflects course difficulty
				for (int i = 1; i <= 5; ++i) rnd_std = rnd_std + irnd_scores[i];
				rnd_std = rnd_std / 5.0;   rndrefsc[i_rc] = rnd_std;
				//  determine crs_ref as a fn of course_rnds
				crS = 0.0;
				// 5 thru 2 downshift, new one becomes 5
				if (course_rnds[i_c] > 5) { for (int i = 1; i < 5; ++i) icrs_ref[i][i_c] = icrs_ref[i + 1][i_c]; icrs_ref[5][i_c] = rnd_std;  crT = 5; }
				if (course_rnds[i_c] < 6) { icrs_ref[course_rnds[i_c]][i_c] = rnd_std; crT = course_rnds[i_c]; }
				//		crF = course_rnds[i_c]; cr0 = course_rnds[i_c - 4]; crT = 5;  
				//	if (course_rnds[i_c] < 5) { crF = course_rnds[i_c]; cr0 = 1; crT = crF; }
				for (int i = 1; i <= crT; ++i) crS = crS + icrs_ref[i][i_c];    //	if(i_c==16)for (int i = 1; i <= crT; ++i) my2file << " crScheck  = " << icrs_ref[i][i_c] << '\n';
				prevcrs_ref[i_c] = crs_ref[i_c];
				crs_ref[i_c] = crS / crT;
				my2file << "  PREV::crs_ref::round  = " << i_rc << " i_c  = " << i_c << " crs_ref[i_c]  = " << crs_ref[i_c] << " prevcrs_ref[i_c]  = " << prevcrs_ref[i_c] << '\n';

				//	crs_ref[i_c] = (crs_ref[i_c] * (course_rnds[i_c] - 1) + rnd_std) / course_rnds[i_c];
				if (i_c == 7)crs_ref[i_c] = rnd_std;  //  if layout is unique unq is code, reference score is from that one specific round only
				//my2file << "  crs_ref::round  = " << i_rc << " i_c  = " << i_c << "  course = " << course[i_rc] << "  course_rnds[i_c] = " << course_rnds[i_c] << "  cur ref score  = " << rnd_std << "  avg ref score crs_ref[i_c] = " << crs_ref[i_c] << '\n';
			}
			rnd_crs_ref[i_rc] = crs_ref[i_c];  //  stores snapshot of crs ref rnd value at time of each round

			//  store orig crs_ref value for pre-2018 season.  Use these in calcs for rnds prior to 2018 season  (background calcs should not include 2018 rnd results in crs_ref values...)
			//if (i_rc == 99) {
			//	for (int j = 1; j <= num_crs; j++) {
			//		o_crs_ref[j] = crs_ref[j];
			//		if (j == 12)o_crs_ref[j] = o_crs_ref[11] - 3.70;
			//		if (j == 20)o_crs_ref[j] = o_crs_ref[19] - 1.50;
			//		//		my2file << "  o_crs_ref::round  = " << i_rc << " j  = " << j << "  course = " << course[i_rc] << "  course_rnds[j] = " << course_rnds[j] << "  cur ref score  = " << rnd_std << "  avg ref score o_crs_ref[j] = " << o_crs_ref[j] << '\n';

			//	}
			//}

			//if (i_rc > 99) {
			//	for (int j = 1; j <= num_crs; j++) {
			//		icrs_ref[i_rc][j] = crs_ref[j];
			//		if (j == 12)icrs_ref[i_rc][j] = icrs_ref[i_rc][11] - 3.70;
			//		if (j == 20)icrs_ref[i_rc][j] = icrs_ref[i_rc][19] - 1.50;
			//		//		if(j==i_c)my2file << "  o_crs_ref::round  = " << i_rc << " j  = " << j << "  course = " << course[i_rc] << "  course_rnds[j] = " << course_rnds[j] << "  cur ref score  = " << rnd_std << "  avg ref score icrs_ref[i_rc][j] = " << icrs_ref[i_rc][j] << '\n';

			//	}
			//}

	

		}  //  end of i_rc loop

		i_rc--;   // corrects number of rounds played
		//	}
		myfile.close();  //  done with player and round data

		my2file << " line 170 done with player and round data  ok i_rc = " << i_rc << '\n';
		//				 //  read in adj score winners data
		//if (winfile.is_open())
		//{
		//	int iw;
		//	for (int j = 1; j <= i_rc; j++) {
		//		iw = 1;
		//		getline(winfile, line);
		//		{
		//			istringstream iss(line);
		//			string word;
		//			while (iss >> word) {
		//				/* do stuff with word */
		//				wins[iw] = word;   iw++;
		//			}
		//			dummy0 = wins[1];  num_win[j] = std::stoi(wins[2]);
		//			if (num_win[j] > 0)for (int k = 3; k <= 3 + num_win[j]; k++)  adj_win[j][k - 2] = wins[k];
		//		}
		//	}
		//}  // end winfile read


		//winfile.close();
		//for (int j = 1; j <= i_rc; j++) {
		//	my2file << " round = " << j << "  " << num_win[j] << " players cashed ::  " << adj_win[j][1] << "  " << adj_win[j][2] << "  " << adj_win[j][3] << "  " << adj_win[j][4] << "  " << adj_win[j][5] << '\n';
		//	//  count number of winning rounds per player
		//	if (num_win[j] > 0) {
		//		num_cash_rnds++;
		//		for (int l = 1; l <= num_win[j]; l++) {
		//			for (int k = 1; k <= i_pl; k++) {
		//				if (player[k] == adj_win[j][l]) { win_count[k]++; break; }

		//			}
		//		}

		//	}
		//}


		//		i_rc--; //  correct irc

		//  organize outputs of course characteristics
//		crs_ref[12] = crs_ref[11] - 3.70;   //  kludge::  reference rounds never occur ad Canadian short tees, based on estimate diff. from yellow tees
//		crs_ref[20] = crs_ref[19] - 1.50;   //  kludge::  reference rounds never occur ad Canadian short tees, based on estimate diff. from yellow tees

											// output course reference scores
		my2file << '\n' << '\n';
		for (int j = 1; j < num_crs; j++) {
			my2file << " course ::  " << courseID[j] << "  hosted " << course_rnds[j] << " rounds.Reference score = " << crs_ref[j] << " HC factor = " << crs_ref[j] / 54.0 << '\n';
			//  "  hosted " << course_rnds[j] <<   // " rounds.  Reference score  =  " << crs_ref[j] << " HC factor   =  " << crs_ref[j] / 54.0 << '\n';
			my2file << '\n';
		}

	}  // end of 	if (myfile.is_open())
	else cout << "unable to open file";

	//	for (int j = 1; j <= i_pl; j++) {  my2file << player[j] << " has hc of: " << hc[j] << '\n';	}  //  ok!  21h11

	my2file << " line 228 done with data reads and prelims  ok i_rc = " << i_rc << '\n';




	//  data has been read in, next is to start organizing and processing it...   **************************************************************************
	//  go through rounds, one by on//e, adding round counts for players, and calculating HCs each round.        *********************************************

	if (1 == 1) {
		 
		

		for (int r = 1; r <= i_rc; r++) {   // +++++++++++++++  all rounds ==  i_rc
			//		for (int r = 1; r <= 1; r++) {   // +++++++++++++++  all rounds ==  i_rc
														//if (r == 2)exit(0);
			my2file << "  NEW ROUND   rnd no.    " << r << "  " << ry[r] << event[r] << "  course :: " << course[r] << '\n' << '\n' << '\n';
			my3file << "  NEW ROUND   rnd no.    " << r << '\n' << '\n' << '\n';
			//int i_count19;  if (event[r].substr(0, 2) == "19")i_count19 = 1; else i_count19 = 0;

			// check if new year, check if HCs have gone stale, if so, reset HC to 3 diffs at HC in current yr, reset num rds to 3
			if (r > 1) {
				if (ry[r] > ry[r - 1]) {
					for (int j = 1; j <= i_pl; j++) {
						if (rnd_count[j] > 2 && ry[r] - d_ry[j][rnd_count[j]] > 2) { //  HC gone stale, effectuate reset !!
							my3file << "  Stale HC ! ! .    " << r << "  " << event[r] << "  " << player[j] << "  " << rnd_count[j] << '\n' << '\n' << '\n';
							rnd_count[j] = 3;
							for (int k = 1; k <= 3; k++) { diff[j][k] = hc[j] / 0.96;	d_ry[j][k] = ry[r]; }
						}

					}
				}
			}
			rnd_size = 0;  rnd_asize = 0;   rnd_sum = 0; rnd_diff = 0.0;
			rnd_rej = 0; q_subzero = 0;  hcmin = 1000;  diff_corr0 = 0.0; diff_corr = 0.0; minDC = 0.0; i_zero_flag = 0; i_zfc = 0; id_zfc = 0;
			//  note course played on::   catalog course id info
			i_c = 0; for (int j = 1; j < num_crs; j++)if (course[r] == courseID[j]) i_c = j;


			if (r <= 99) c_fac = o_crs_ref[i_c] / 54.0;  //  my2file << "  cfac =    " << c_fac << "  crs_ref[i_c] =    " << crs_ref[i_c] <<'\n';
			if (r > 99) c_fac = icrs_ref[r][i_c] / 54.0;  //  my2file << "  cfac =    " << c_fac << "  crs_ref[i_c] =    " << crs_ref[i_c] <<'\n';
			//	 c_fac = 1;   // can activate this line to compare to cases without round difficulty correction
			oc_fac = prevcrs_ref[i_c] / 54.0; c_fac = crs_ref[i_c] / 54.0;
			if (prevcrs_ref[i_c] == 0)oc_fac = c_fac;
			//		my2file << " line304 ok i_rc = " << i_rc << "c_fac = " << c_fac << '\n';
			for (int j = 1; j <= i_pl; j++) {  // store hc into hc0 for current round results
				hc0[j] = hc[j];
			}
			//	my2file << " line276 ok i_rc = " << i_rc << "johnny's round total = " << rnd_count[94] << '\n';

			for (int j = 1; j <= i_pl; j++) {  // check players to see if they were in round
				if (score[r][j] > 0) { // if player_j played this round incr rnd count, put into pool for rnd calcs
					rnd_count[j]++;   rnd_size++; player_pt[rnd_size] = j;
					//		 		my2file << " player in   rnd no.    " << r << " j_index  " << j << " name::  " << player[j] << " no. rds =  " << rnd_count[j] << " HC =  " << hc[j] << '\n';
								//	if (i_count19 == 1)toss19_rnd_count[j]++;
									// j==76 stevePike

					rnd_scores[rnd_size] = score[r][j]; irnd_scores[rnd_size] = score[r][j]; hc_gen[rnd_size] = hc0[j] * oc_fac; hc_gen0[rnd_size] = hc0[j];  if (hc0[j] < 0)hc_gen[rnd_size] = 0;  rnd_adj_gen[rnd_size] = score[r][j] - hc0[j] * c_fac; if (rnd_count[j] <= 3) rnd_adj_gen[rnd_size] = score[r][j];

					if (hc[j] > -0.9) {   // players with less than 3 rounds (ie; no HC) excluded from this calc.
						rnd_asize++; rnd_ascores[rnd_asize] = score[r][j];
						rnd_adj_sc[rnd_asize] = score[r][j] - hc0[j] * c_fac; rnd_hc[rnd_asize] = hc0[j] * c_fac;
						rnd_diff = rnd_diff + rnd_adj_sc[rnd_asize];
						//	if (player_pt[rnd_size] == 43)	my3file << " Yuriy_round no. =  " << r << " player =  " << player[player_pt[rnd_size]] << " rnd score =  " << score[r][j] << " rnd_adj_sc[rnd_asize] =  " << rnd_adj_sc[rnd_asize] << " rnd_diff =  " << rnd_diff << '\n';
					}
					if (hc[j] > -0.9) rnd_sum = rnd_sum + score[r][j];
				}
			}  // end of check players

		//	my2file << " line297 ok i_rc = " << i_rc << "johnny's round total = " << rnd_count[94] << '\n';

			   // calcuate round-related values
			rnd_scratch = rnd_diff / rnd_asize;  // unfiltered 

			rnd_mean = rnd_sum / rnd_asize;
			my2file << " before filter:  rnd_scores  " << rnd_scores[rnd_asize] << "  rnd_Adjsize  " << rnd_asize << "  rnd_mean  " << rnd_mean << "  rnd_ref_sc  " << rndrefsc[r] << '\n';
			//   sort adjusted scores to find adjusted winners of round
			//  code below creates a pointer array for adjScore ranks
			for (int j = 1; j <= rnd_size; j++) rank_as[j] = j;
			int ashold;
			for (int ij = 1; ij <= rnd_size - 1; ij++) {
				for (int j = 1; j <= rnd_size - ij; j++) {
					if (rnd_adj_gen[rank_as[j]] > rnd_adj_gen[rank_as[j + 1]]) {
						ashold = rank_as[j]; rank_as[j] = rank_as[j + 1]; rank_as[j + 1] = ashold;
					}
				}
			}
			//  compares adj scores by rank   //   
			for (int j = 1; j <= rnd_size; j++) {
				//  if rank is within the number of cashing players, add to count of simulated winning rounds
				if (j <= num_win[r])my2file << " rank =  " << j << "  " << player[player_pt[rank_as[j]]] << "  Adj Score =  " << rnd_adj_gen[rank_as[j]] << "  rounds played = " << rnd_count[player_pt[rank_as[j]]] << "  real player  = " << adj_win[r][j] << '\n';
				if (j > num_win[r])my2file << " rank =  " << j << "  " << player[player_pt[rank_as[j]]] << "  Raw Score =  " << rnd_scores[rank_as[j]] << "  hc =  " << hc_gen[rank_as[j]] << "  Adj Score =  " << rnd_adj_gen[rank_as[j]] << "  hc0 ..  cfac  = " << hc_gen0[rank_as[j]] << "  " << c_fac << '\n';
				if (j <= num_win[r])sim_win_count[player_pt[rank_as[j]]]++;
			}

			//  calc std deviation of adjusted scores
			rnd_stdev = stdev(rnd_adj_sc, rnd_scratch, rnd_asize);

			// filter round to remove abnormally poor adjusted scores > 1.4*std dev above mean
			rnd_upperFilter = rnd_scratch + 1.40 * rnd_stdev;
			my3file << "  rnd no.    " << r << "  rnd_upperFilter     " << rnd_upperFilter << "  rnd score =    " << score[r][76] << "  HC =    " << hc[76] << '\n';
			for (int j = 1; j <= rnd_asize; j++) {  // loop to filter outlier scores
				if (r > 98)my3file << " rejtest::round no. =  " << r << " player =  " << player[player_pt[j]] << " rnd_upperFilter =  " << rnd_upperFilter << "  rnd_adj_sc[j] = " << rnd_adj_sc[j] << '\n';

				if (rnd_adj_sc[j] > rnd_upperFilter) {
					//	if(playerJ is steve pike)write out  player_pt[rnd_size]
					if (player_pt[j] == 76)my3file << " rej::round no. =  " << r << " player =  " << player[player_pt[j]] << " rnd_upperFilter =  " << rnd_upperFilter << "  rnd_adj_sc[j] = " << rnd_adj_sc[j] << '\n';
					rnd_rej++;  // count up rejected filtered scores
					rnd_diff = rnd_diff - rnd_adj_sc[j];  // removed filtered differentials
				}
			}
			//  determine round scratch and slope

			rnd_scratch = rnd_diff / (rnd_asize - rnd_rej);
			//		rnd_scratch = min(rnd_scratch, rnd_diff / (rnd_size - rnd_rej));  // don't use filter if it makes scratch go UP !
			my2file << "  round no.   " << r << " scratch score = " << rnd_scratch << " ref score = " << rnd_crs_ref[r] << " course = " << courseID[i_c] << '\n';
			//			for (int j = 1; j <= rnd_size; j++) my2file << " before regr  j = " << j << " rnd_scores[j] =  " << rnd_scores[j] << '\n';
			for (int j = 1; j <= rnd_asize; j++) rnd_sc_delta[j] = rnd_ascores[j] - rnd_scratch;
			// perform regression on round scores to get slope
			leastSqrRegression(rnd_sc_delta, rnd_hc, rnd_asize, rval, slp, yint);

			//	for (int j = 1; j <= rnd_size; j++) my2file << " after regr  j = " << j << " rnd_scores[j] =  " << rnd_scores[j] << '\n';

			toest = slp * 113;   // normalize slope to 113  (golf convention)
			//		slp = min(max(65.0, toest), 165.0);  //  restrict to conventional 65 to 165 range
			slp = min(max(95.0, toest), 165.0);  //  restrict to conventional 65 to 165 range
			my2file << " round slope value :: " << slp << endl;

			//  calculate differentials
			for (int j = 1; j <= rnd_size; j++) {
				//	 diff[player_id][rnd_count(playerJ)] = (H144 - sc_avgf)*(113 / slp)
				int k = player_pt[j]; //  player k in round r, ID'd through pointer as player k in global list  //  my2file << "  player_pt[j] = " << k << '\n'; cout << "  player_pt[j] = " << k << '\n';
				//  differential calculation, scaled by c_fac (course difficulty factor), small cfac increases diff, large cfad reduces it
				diff[k][rnd_count[k]] = (rnd_scores[j] - rnd_scratch) * (113 / slp) / c_fac;
				d_ry[k][rnd_count[k]] = ry[r]; // rnd_count's  rnd of player k tagged with year from ry[r]
				if (player_pt[j] == 43)my3file << " diff::round no. =  " << r << " player =  " << player[player_pt[j]] << " rnd score =  " << score[r][k] << "  rnd_scratch = " << rnd_scratch << " diff[k][rnd_count[k]] = " << diff[k][rnd_count[k]] << " No. plyr's rds::rnd_count[k]  = " << rnd_count[k] << " rd year  = " << d_ry[k][rnd_count[k]] << '\n';
				//  next update HCdiff[k][
				int i_in; i_in = 1;  if (rnd_count[k] > 20)i_in = rnd_count[k] - 19; //  i_in is low value of index for array to get to 20 most recent diffs.
				for (int i = i_in; i <= rnd_count[k]; i++) { int in = i - i_in + 1; dfk[in] = diff[k][i];  ryfk[in] = d_ry[k][i]; }  //  dfk is single index array, used to shuttle diff values for each player to HC function
				if (player_pt[j] == 18) {
					for (int in = 1; in < 21; in++)
						my3file << " diff::round no. =  " << r << " player =  " << player[player_pt[j]] << " in =  " << in << " dfk[in] =  " << dfk[in] << " diff[player_pt[j]][in_last20] =  " << diff[player_pt[j]][rnd_count[22] - 20 + in] << " diff[player_pt[j]][in] =  " << diff[player_pt[j]][in] << " ry = " << ryfk[in] << '\n';
				}


				double oldhc = hc[k];  int irck; irck = rnd_count[k];  if (rnd_count[k] > 20) irck = 20;
				// calc HC, inputs are array of diffs and number of rounds played
				if (rnd_count[k] > 2) hc[k] = hcc(dfk, irck);
				if (player_pt[j] == 49)my3file << " diff::round no. =  " << r << " player =  " << player[player_pt[j]] << " old hc =  " << oldhc << "  updated HC = " << hc[k] << '\n';


				//  check if HC goes sub-zero, if so, there will be adjustments required...
				//	if (rnd_count[k] > 2) if (hc[k] < q_subzero) {
				if (rnd_count[k] > 2) if (hc[k] < 0.0) {
					my2file << " inside sub_zero check  " << hc[k] << " player  = " << player[player_pt[j]] << '\n' << '\n' << '\n';
					q_subzero = hc[k]; qzeroHCid = k;
					i_zero_flag = 1; i_zfc++;
					ss_id[i_zfc] = player_pt[j];
					if (irck < 3) numc = 0; if (irck > 2 && irck < 6) numc = 1; if (irck > 5 && irck < 9) numc = 2; if (irck > 8 && irck < 11) numc = 3; if (irck > 10 && irck < 13) numc = 4;
					if (irck > 12 && irck < 15) numc = 5; if (irck > 14 && irck < 17) numc = 6; if (irck == 17) numc = 7;  if (irck == 18) numc = 8; if (irck == 19) numc = 9; if (irck >= 20) numc = 10;
					diff_corr0 = q_subzero * numc / 0.96 / 10;  // differential correction value req'd to coherently reset all HCs such that lowest HC is zero	 
					ss_diff_corr[i_zfc] = diff_corr0;  ss_numc[i_zfc] = numc;
					diff_corr = min(diff_corr, diff_corr0);
					if (diff_corr == ss_diff_corr[i_zfc]) { id_zfc = ss_id[i_zfc]; }
					if (diff_corr == ss_diff_corr[i_zfc]) {
						numcz = ss_numc[i_zfc];
					}
					q_subzero = hc[id_zfc]; qzeroHCid = id_zfc;

				}  // end of subzero section

			}   cout << " done differential loop " << '\n';
			//	my2file << "line 344 " << " low diff corr player is: " << player[id_zfc] << " numcz : " << numcz << endl;
			// check if there is an HC conflict among subs-scratches and correct
			if (i_zfc > 55) {
				for (int j = 1; j <= i_zfc; j++) {
					// list player and stats
					my2file << " inside sub_zero reviews j=  " << j << " rnd = " << r << " hc = " << hc[ss_id[j]] << " diff_corr = " << ss_diff_corr[j] << " player  = " << player[ss_id[j]] << " player numc = " << ss_numc[i_zfc] << '\n' << '\n' << '\n';
					my2file << " differentials for player no.  " << j << "  " << j << '\n';
					int rd_st;  if (rnd_count[ss_id[j]] > 19) rd_st = rnd_count[ss_id[j]] - 19; else rd_st = 1;
					for (int jj = rd_st; jj <= rnd_count[ss_id[j]]; jj++) {
						my2file << " differential jj  " << jj << "  " << diff[ss_id[j]][jj] << '\n';

						//  identify which diff_corr will define zero HC


					}
				}

				//	int k = player_pt[j]; //  player k in round r, ID'd through pointer as player k in global list  //  my2file << "  player_pt[j] = " << k << '\n'; cout << "  player_pt[j] = " << k << '\n';
				//  differential calculation, scaled by c_fac (course difficulty factor), small cfac increases diff, large cfad reduces it
				//	diff[k][rnd_count[k]] = (rnd_scores[j] - rnd_scratch)*(113 / slp) / c_fac;
				//	if (player_pt[j] == 49)my3file << " diff::round no. =  " << r << " player =  " << player[player_pt[j]] << " rnd score =  " << score[r][k] << "  rnd_scratch = " << rnd_scratch << " diff[k][rnd_count[k]] = " << diff[k][rnd_count[k]] << '\n';
				//	//  next update HC
				//	int i_in; i_in = 1;  if (rnd_count[k] > 20)i_in = rnd_count[k] - 19; //  i_in is low value of index for array to get to 20 most recent diffs.



			}
			//  next shift all HCs if a player went sub-zero
			//	my2file << " line 372 id_zfc =   " << id_zfc << "  id  =   " << player[id_zfc] << "  q_subzero =  " << q_subzero << "  qzeroHCid  =   " << qzeroHCid << '\n';
			for (int j = 1; j <= i_pl; j++) { if (hc[j] < hcmin && rnd_count[j] > 2) { ID_hcmin = j; hcmin = min(hcmin, hc[j]); } }
			//	 if(r==204)my2file << " line 374 hcmin =   " << hcmin << "  id  =   " << player[ID_hcmin] << '\n';

			for (int j = 1; j <= i_pl; j++) { if (j == id_zfc && rnd_count[j] > 2) { ID_hcmin = j; hcmin = min(0.0, hc[j]); } }
			// 	   my2file << " line 377 hcmin =   " << hcmin << "  id  =   " << player[ID_hcmin] << "  r  =   " << r << '\n';


			// 		 my2file << " redunCHeck  hcmin  " << hcmin << " lowest HC q_subzero  = " << q_subzero << " qzeroHCid  = " << qzeroHCid  << "  ID_hcmin  = " << ID_hcmin << '\n';
			//		my2file << "line 381 " << endl;
			my2file << " after round  " << r << " lowest HC  = " << hcmin << " diff-corr  = " << diff_corr << "  player  = " << player[ID_hcmin] << "  i_zero_flag  = " << i_zero_flag << '\n' << '\n' << '\n';
			my3file << " after round  " << r << " lowest HC  = " << hcmin << " diff-corr  = " << diff_corr << "  player  = " << player[ID_hcmin] << "  i_zero_flag  = " << i_zero_flag << '\n' << '\n' << '\n';
			if (i_zero_flag == 1) {
				my2file << "line 384 " << endl;
				for (int j = 1; j <= i_pl; j++) {
					//		 my2file << player[j] << "before corrn  HC =  " << hc[j] << "  rounds played = " << rnd_count[j] << '\n';
					if (rnd_count[j] > 2) hc[j] = hc[j] - q_subzero * numcz / 10; if (j == qzeroHCid) {
						hc[j] = 0; // for all rnds from now back numc, set diff values to 0
						if (numcz < 10 && 1 == 1)for (int l = rnd_count[j]; l > rnd_count[j] - numcz; l--)  diff[j][l] = 0.0;
					}  // set numc most recent diffs for zero-player to 0 to keep HC calc at zero
					   //		 my2file << player[j] << "after corrn  HC =  " << hc[j] << "  rounds played = " << rnd_count[j] << '\n';

					   //  if we have a sub-zero round, all differentials need to be upshifted by the negative leading portion
					   //    also HCs need to be upshifted by same degree as the leading subzero player
					for (int l = 1; l <= rnd_count[j]; l++) {
						//if (r == 204 && j == qzeroHCid)my2file << " pre: l =  " << l << " diff[j][l] =  " << diff[j][l] << " diff_corr =  " << diff_corr << " numc =  " << numc << '\n';
						//	if (r == 204 && j == 20)my2file << " pre20: l =  " << l << " diff[j][l] =  " << diff[j][l] << " diff_corr =  " << diff_corr << '\n';
						diff[j][l] = diff[j][l] - diff_corr;
						//if (r == 204 && j == qzeroHCid)my2file << " post: l =  " << l << " diff[j][l] =  " << diff[j][l] << '\n';
						//if (r == 204 && j == 20)my2file << " post20: l =  " << l << " diff[j][l] =  " << diff[j][l] << " id =  " << player[j]  << '\n';
					}
					// for (int j = 1; j <= rnd_size; j++) my2file << " at end  j = " << j << " rnd_scores[j] =  " << rnd_scores[j] << '\n';
				}
			}

			//		my2file << "preSZ =    name  = " << player[player_pt[j]] << '\n';
			// check to see if multi-subzero and correct
			if (i_zfc > 1 && r == 204) {  //  largest diff_core will get 0 HC
				for (int j = 1; j <= i_zfc; j++) {
					my2file << "multi-subzero  lowSSid  =  " << low_ssID << "  name  = " << player[low_ssID] << "   id_zfc  = " << id_zfc << '\n';
					if (ss_id[j] != id_zfc) {
						// change non - low - diff - core subScratch players HC and residuals
						double	last_resid = ss_diff_corr[i_zfc] - diff_corr;
						my2file << "multi-subzero  j  =  " << j << " id  = " << ss_id[j] << " ss_diff_corr[i_zfc]  = " << ss_diff_corr[i_zfc] << " ss_diff_corr[id_zfc]  = " << ss_diff_corr[id_zfc] << "  diff_corr   = " << diff_corr << "  last_resid  =  " << last_resid << '\n';
						my2file << "multi-subzero  player rnd cnt j  =  " << rnd_count[ss_id[j]] << "  last_residual  =  " << diff[ss_id[j]][rnd_count[ss_id[j]]] << '\n';
						hc[ss_id[j]] = 0.93 * last_resid; diff[ss_id[j]][rnd_count[ss_id[j]]] = last_resid;
					}

					//if(r>200)exit(0);  id_zfc
				}
			}



		}  // end of processing one round
	}  // if(1==2)  loop on index r, round counter

	if (1 == 1) {
		ofstream prfile("player_rounds.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data

		for (int j = 1; j <= i_pl; j++) {
			// check if HC too high, max out at 36
			if (rnd_count[j] > 2 && hc[j] > 36.0)hc[j] = 36.0;

			//	my2file << player[j] << " HC =  " << hc[j] << "  rounds played = " << rnd_count[j] - in_rnd_count[j] << '\n';
			prfile << player[j] << " HC =  " << hc[j] << "  rounds played = " << rnd_count[j] - in_rnd_count[j] << '\n';
		}
		//my2file << '\n' << '\n';
		////  output player/rounds/times cashed...
		//for (int k = 1; k <= i_pl; k++) {
		//	int itest; itest = rnd_count[k] - in_rnd_count[k];
		//	if (itest > 10 && rnd_count[k] > 2) my2file << player[k] << " real times cashed =  " << win_count[k] << " sim. cashed =  " << sim_win_count[k] << "  rounds = " << itest << " HC =  " << hc[k] << " frac. rounds cashed =  " << float(win_count[k]) / itest << " frac sim cashed =  " << float(sim_win_count[k]) / itest << '\n';

		//}
	}   //  end(1==2) loop, can activate to look at times cashing for code development...

		//  sort HCs for printing
	ofstream rkfile("rankHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data

	for (int j = 1; j <= i_pl; j++) rank_hc[j] = j;
	int hhold;
	for (int ij = 1; ij <= i_pl - 1; ij++) {
		for (int j = 1; j <= i_pl - ij; j++) {
			if (hc[rank_hc[j]] > hc[rank_hc[j + 1]]) {
				//	my2file << " ranking if YES!  j =  " << j << "  hc[j] = " << hc[j] << "  hc[j+1] = " << hc[j + 1] << "  rank_hc[j] = " << rank_hc[j] << "  rank_hc[j+1] = " << rank_hc[j + 1] << '\n';

				hhold = rank_hc[j]; rank_hc[j] = rank_hc[j + 1]; rank_hc[j + 1] = hhold;
			}
			// my2file << "  sort:  when ij =  " << ij  << '\n'; for (int j = 1; j <= 5; j++) my2file << " j = " << j << "  rank_hc[j] = " << rank_hc[j] << '\n';
		}
	}
	rkfile << '\n' << '\n';  //  HCs by rank
	int i_rank; i_rank = 0;
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[rank_hc[j]] > 2) {
			i_rank++;
			my2file << " rank =  " << i_rank << "  " << player[rank_hc[j]] << " HC =  " << hc[rank_hc[j]] << "  rounds played = " << rnd_count[rank_hc[j]] - in_rnd_count[rank_hc[j]] << '\n';
			rkfile << " rank =  " << i_rank << "  " << player[rank_hc[j]] << " HC =  " << hc[rank_hc[j]] << "  rounds played = " << rnd_count[rank_hc[j]] - in_rnd_count[rank_hc[j]] << '\n';
		}
	}


	if (1 == 2) {
		//  populate 3 differentials based on   HC  
		//  first operation: store handicapp and ten pseudo-rounds after HC data rupture at end of 2014...
		//  players with HCs get round count of 10, else they are set at zero rounds
		double difreset;  	my2file << '\n' << '\n';  //  HCs by rank
		my2file << '\n' << '\n';  //  HCs by rank

		for (int j = 1; j <= i_pl; j++) {
			if (hc[j] > -0.9) { difreset = hc[j] / 0.96; 	my2file << j << "  " << difreset << "  " << difreset << "  " << difreset << '\n'; }
			if (hc[j] < -0.9 && rnd_count[j] == 1)my2file << j << "  " << diff[j][1] << "  " << 99.9 << "  " << 99.9 << '\n';
			if (hc[j] < -0.9 && rnd_count[j] == 2)my2file << j << "  " << diff[j][1] << "  " << diff[j][2] << "  " << 99.9 << '\n';
		}
	}
	my2file << '\n' << '\n';  //  HCs by rank
	my2file << '\n' << '\n';  //  HCs by rank






	//my2file << '\n' << '\n';  //  players without 3 rounds for HC
	//my2file << " no hc count  total number of players  =  " << i_pl << '\n';
	//int i_nohc; i_nohc = 0;    //  output all 116 HCs in row for restart data file
	//for (int j = 1; j <= i_pl; j++) {
	//	//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
	//	if (rnd_count[rank_hc[j]] < 3) {
	//		i_nohc++;
	//		my2file << " no hc count  =  " << i_nohc << "  " << player[rank_hc[j]] << '\n';
	//	}
	//}

	my2file << '\n' << '\n';  //  HCs in alphabetical order
	ofstream alffile("alphHC.txt");  //  output file, collects diagnotistic, debugging info, as well as final HC list and simulated list of round results using updated model over the 3 seasons worth of data

	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			string memboo; if (mem_stat[j] == 1)memboo = "YES"; if (mem_stat[j] == 0)memboo = "NO";
			alffile << player[j] << " HC =  " << hc[j] << "  rounds played = " << rnd_count[j] - in_rnd_count[j] << "  current member? - " << memboo << " 2019TOSSrnds = " << toss19_rnd_count[j] << '\n';
			my3file << " playerIDno. =  " << j << "  " << player[j] << " HC =  " << hc[j] << "  rounds played = " << rnd_count[j] - in_rnd_count[j] << "  current member? - " << memboo << " 2019TOSSrnds = " << toss19_rnd_count[j] << '\n';
		}
	}
	//  same loop as above prints for Dan Phillips - Kemptville Club
	kvfile << '\n' << "Kemptville_courses_HC_list    base54HC Ferguson   Mountain  " << '\n';  //  "kpv", "mtn" 
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			kvfile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] << "   " << hc[j] * crs_ref[12] / 54.0 << "   " << hc[j] * crs_ref[13] / 54.0 << "   " << hc[j] * crs_ref[1] / 54.0

				<< '\n';
		}
	}


	//  same loop as above ONLY prints for ODGC paid-up members   odgccafile
	tossfile << '\n' << "ODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_blue   Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown Camp_Fortune" << '\n';  //  "lmb", "lmy", "alm", "kan",
	odgccafile << '\n' << "  name    base54HC " << '\n';  //  "lmb", "lmy", "alm", "kan",
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			string ODGCmemboo; if (ODGCmem_stat[j] == 1)ODGCmemboo = "YES"; if (ODGCmem_stat[j] == 0)ODGCmemboo = "NO";
			if (ODGCmem_stat[j] == 1) tossfile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] << "   " << hc[j] * crs_ref[8] / 54.0 << "   " << hc[j] * crs_ref[9] / 54.0 << "   " << hc[j] * crs_ref[22] / 54.0 << "   " << hc[j] * crs_ref[11] / 54.0 << "   " << hc[j] * crs_ref[13] / 54.0 << "   " << hc[j] * crs_ref[25] / 54.0 << "   " << hc[j] * crs_ref[17] / 54.0 << "   " << hc[j] * crs_ref[21] / 54.0 << "   " << hc[j] * crs_ref[15] / 54.0 << "   " << hc[j] * crs_ref[18] / 54.0 << "   " << hc[j] * crs_ref[24] / 54.0 << '\n';
			if (ODGCmem_stat[j] == 1) odgccafile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] << '\n';

		}
	}
	//  add to ODGC HC File  course stats...
	//  course info data
	int nnm = 22;
	string cnm[] = { " ","The_Shire","Kanata","Larrimac","Larrimac","Larrimac","Almonte","Almonte","Almonte","Ettyville_MVP","Ettyville_MVP","Ettyville_MVP","Ettyville_Axiom","Ettyville_Axiom","Ettyville_Axiom","Kemptville","Kemptville","Kemptville","Camp_Fortune","Franktown","Phillips_Screwdriver","UPI","Centrepointe"};
	int icnm[] = { 0,15,11,5,8,9,26,22,23,1,2,3,4,5,6,21,17,25,24,18,13,16,27 };

	odgccafile << '\n' << '\n';
	for (int j = 1; j <= nnm; j++) {
	//	my2file << " course ::  " << cnm[j] << "  hosted " << course_rnds[icnm[j]] << " rounds.  Reference score  =  " << crs_ref[icnm[j]] << "  HC factor   =  " << crs_ref[icnm[j]] / 54.0 << '\n';
		odgccafile   << cnm[j] << "   " << crs_ref[icnm[j]] << "   " << crs_ref[icnm[j]] / 54.0 << '\n';
		//odgccafile << '\n';
	}
	//  same loop as above ONLY prints for ODGC paid-up members and a few other TOSS eligble people for Mark Atos
	Atosfile << "ODGC_courses_HC_list    base54HC LmacBlue  LmacYellow Almonte_Blue  Almonte_Yellow  Kanata   Mountain  KvYel KvBlue KvRed Shire Franktown Camp_Fortune" << '\n';  //  "lmb", "lmy", "alm", "kan",
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			string TOSSmemboo; if (TOSSmem_stat[j] == 1 || ODGCmem_stat[j] == 1)TOSSmemboo = "YES"; if (ODGCmem_stat[j] == 0)TOSSmemboo = "NO";
			if (TOSSmem_stat[j] == 1 || ODGCmem_stat[j] == 1) Atosfile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] << "   " << hc[j] * crs_ref[8] / 54.0 << "   " << hc[j] * crs_ref[9] / 54.0 << "   " << hc[j] * crs_ref[22] / 54.0 << "   " << hc[j] * crs_ref[23] / 54.0 << "   " << hc[j] * crs_ref[11] / 54.0 << "   " << hc[j] * crs_ref[13] / 54.0 << "   " << hc[j] * crs_ref[25] / 54.0 << "   " << hc[j] * crs_ref[17] / 54.0 << "   " << hc[j] * crs_ref[21] / 54.0 << "   " << hc[j] * crs_ref[15] / 54.0 << "   " << hc[j] * crs_ref[18] / 54.0 << "   " << hc[j] * crs_ref[24] / 54.0 << '\n';
		}
	}
	//  same loop as above ONLY prints for EV purposes
	evfile << "EV_courses_HC_list   MVP_WHI  MVP_BLU  MVP_YEL   AxiomWHI  AxiomBLU  AxiomYEL " << '\n';
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			string EVmemboo; if (EVmem_stat[j] == 1 && ODGCmem_stat[j] == 1)EVmemboo = "YES"; if (EVmem_stat[j] == 0)EVmemboo = "NO";
			if (EVmem_stat[j] == 1 || ODGCmem_stat[j] == 1) evfile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] * crs_ref[1] / 54.0 << "   " << hc[j] * (crs_ref[3]-3.21) / 54.0 << "   " << hc[j] * crs_ref[3] / 54.0 << "   " << hc[j] * crs_ref[4] / 54.0 << "   " << hc[j] * (crs_ref[6]-2.05) / 54.0 << "   " << hc[j] * crs_ref[6
			] / 54.0 << '\n';
		}
	}

	//  same loop as above ONLY prints for LadiesLeague purposes
	cmfile << '\n' << "LL_courses_HC_list   base54HC  Kanata " << '\n';
	for (int j = 1; j <= i_pl; j++) {
		//	my2file <<   " j =  " << j  << "  rank_hc[j] = " << rank_hc[j]  << '\n';
		if (rnd_count[j] > 2) {
			string LLmemboo; if (LLmem_stat[j] == 1)LLmemboo = "YES"; if (LLmem_stat[j] == 0)LLmemboo = "NO";
			if (LLmem_stat[j] == 1 && ODGCmem_stat[j] == 1) cmfile << player[j] << "   " << std::fixed << std::setprecision(2) << hc[j] << "   " << hc[j] * crs_ref[11] / 54.0 << '\n';
		}
	}
	//  organize outputs of course characteristics
	my2file << '\n' << '\n';
	for (int j = 1; j < num_crs; j++) {
		my2file << " course ::  " << courseID[j] << "  hosted " << course_rnds[j] << " rounds.  Reference score  =  " << crs_ref[j] << "  HC factor   =  " << crs_ref[j] / 54.0 << '\n';
		my2file << '\n';


	}

	my2file.close();




	do {
		//allowing the user to quit

		cout << "Do you want to quit?" << endl;
		cout << "If so, press 0." << endl;
		cout << "  press anything else." << endl;
		cin >> quitOrNo;

		//if characters are input into the quit variable
		if (quitOrNo >= 0 || quitOrNo <= 0) {
			cin.clear();
			cin.ignore(numeric_limits<streamsize>::max(), '\n');
		}

	} while (quitOrNo != 0);  //allowing the user to do more than one conversion 

	system("pause");
	return 0;

	system("pause");
}  // end main

