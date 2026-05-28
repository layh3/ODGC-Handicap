
	const int n_player = 500; const int n_rounds = 500;  // array indexes n_player== total number of players, n_rounds==total number of rounds played
  	int i_pl; i_pl = 0;  // index ID for player
    int i_rc;  i_rc = 0;  // index number for r rounds
    static int cr0, crF, crT;   static double crS;    static int jin;
    	int i_c; //  index ID for courses
     const int num_crs = 28;   // total number of different courses, includes layout variations of a course
//      string courseID[] = { "jeu", "alc", "shr", "kan", "cfs", "cfl", "mtn", "evm", "evp", "k27", "cfb", "cal", "cas", "alm", "mnb", "evn", "mt9", "ev1", "kss", "lml", "lmm", "twl", "lmy", "lmb", "lmr", "cf9", "rgn", "evd", "evb",  "unq", "evy" , "evi" , "evw" , "eil", "eiw" };    //  array of strings IDing each course we play on
      string courseID[] = { "jeu", "epw", "epb", "epy", "eiw", "eib", "eiy", "unq", "lmb", "lmy", "alm0", "kan", "kpv","mtn","cur", "shr", "upi", "kvb", "ffw" , "rhl", "alm", "kvr", "alb", "aly", "cf", "kvy", "alr", "ctp"};    //  array of strings IDing each course we play on
//      string courseID[] = { "jeu", "alc", "shr", "kan", "cfs", "cfl", "mtn", "evm", "evp", "k27", "cfb", "cal", "cas", "alm", "mnb", "evn", "mt9", "ev1", "kss", "lml", "lmm" };    //  array of strings IDing each course we play on
	int course_rnds[num_crs] = { 0 };   // counter array for number rounds played on Nth course  
 static  string course[n_rounds]; 
   static string event[n_rounds];  //  name of course of nth round; event details of nth round
 //  	double crs_fac[] = { 0, 58.2667, 52.125, 48.35, 52.3636, 59.0, 57.5, 63.0, 72.1,  70.7333, 55.4, 59.9,  56.2,  53.08, 65.2, 54.4,  57.3 };  //  above, array of difficulty factors, used to test code in early version, now this factor is updated automatically as more rounds are played...
 cout <<  "  in initialize_variables.H ! !  " << endl;
 
  static double c_fac; static double oc_fac;
 
	string line;    //  generic line of text from input file  roundData.dat
  string wins[10];     // number of players cashing in a given round
	string player[n_player];   // names of players  (roundData.dat)
   static int mem_stat[n_player]; // ODGC membership status of player ==0 non-member  ==1 member
   static int ODGCmem_stat[n_player]; // ODGC membership status of player ==0 non-member  ==1 member
   static int TOSSmem_stat[n_player]; // TOSSmembership status of player ==0 non-member  ==1 member  (list for Mark Atos vs. "formal" list of paid dues members)
   static int EVmem_stat[n_player]; // Ettyville membership status of player ==0 non-member  ==1 member   
   static int LLmem_stat[n_player]; // LadiesLeague membership status of player ==0 non-member  ==1 member   
   static double hc[n_player];   // hc of nth player,  in some cases read from end of 2014 value from (roundData.dat), or initialized as -1 if player's 1st round comes sometime later
   static double hc0[n_player];   // old hc of nth player, value going in to current round;  in some cases read from end of 2014 value from (roundData.dat), or initialized as -1 if player's 1st round comes sometime later
   static double hc_gen[n_player], hc_gen0[n_player];
   static double diff[n_player][n_rounds];  //  array of differentials for nth player, over N rounds
   static int rnd_count[n_player]; static int in_rnd_count[n_player] = {};  static int toss19_rnd_count[n_player] = {};  //  rounds played by nth player, initial (pre-2015) round count for nth player, set to 10 for players with existing HCs, otherwise 0
  int score[500][500]; string dummy, dummy0 ;  // local array of scores for round r ,     indexes [player N of round r][player P globally]
  	int rnd_size;  rnd_size = 0;  // number of players in round r
    double rnd_sum; double rnd_diff; rnd_sum = 0; rnd_diff = 0.0;   //  total sum of scores from round r,  total sum of differentials from round r
    double rnd_stdev;   //  standard deviation of adjusted scores from round r
  static double rnd_scores[90];	static int irnd_scores[90];  static double rnd_hc[90];  //  array of scores from round r, integer array of same scores, HCs linked to these scores
   double rnd_mean; int rnd_rej; rnd_rej = 0;    // average round score, number of filtered rounds      
  double rnd_sc_delta[90];  //    rnd_sc_delta[j] = rnd_ascores[j] - rnd_scratch
 	static double crs_ref[35] = { 0.0 };   //  array of avg ref score values for nth course
 	static double prevcrs_ref[35] = { 0.0 };   //  array of avg ref score values for nth course after previous round
  static double rndrefsc[n_rounds] ; // stored array of ref score for particular round
 	static double icrs_ref[6][num_crs] = { 0.0 };   //  array of avg ref score values for nth course
 	static double o_crs_ref[35] = { 0.0 };   //  array of  orig avg ref score values for nth course, in effect for first 99 rounds background base calc
	static double   rnd_crs_ref[n_rounds]  ; //  array of ref scores on a round by round basis, gives evolution of ref_score for a given layout over time
	 static int ry[n_rounds]  ; //  2 digit year in which round took place; used for eliminating old data for 2yr HC time limit...
	static int   d_ry[n_player][n_rounds]  ; //  array of years rounds took place in, for nth player, over N rounds
   static int player_pt[90];       // pointer array linking player j in round r, to player n in global list  ie; for round r, player[player_pt[j]] = n
   double toest;  static double dfk[21];   // intermediate parameter in slope calc; local array of player's last-20 differentials sent to HCcalc function
  static int ryfk[21];   // intermediate parameter in slope calc; local array of player's last-20 rnd yrs used to regulate number of rounds counted.
   static double rnd_scratch;   // local value of scratch score in round, == avg of adjusted scores, with outliers (> 1.4 x std_dev )  filtered out
   	static double rnd_std;  // avg value of top 5 raw scores in a round, used to characterize course ref value.
   double rval, slp, yint;      //  arguments for HC function, regression coeff, slope, y-intercept
   double rnd_upperFilter;    //  =avg_adjusted_score +   1.4 x std_dev ;  any adjusted scores above this value are excluded from scratch determination
 	static double rnd_adj_sc[90]; static double rnd_adj_gen[90];    //  nth adjusted score of round r;  general  nth adjusted score of round r, used for sorting results not calcuations  ie; these can include scores for players not yet having established a HC
   int rnd_asize;  rnd_asize = 0; static double rnd_ascores[90];   //  filter number of scores in round r;  array of filtered scores from round r
 	double q_subzero; q_subzero = 0; int qzeroHCid;    // extent of HC going below zero (should it occur in a round);  index of player moving to subzero HC
   int ID_hcmin; double hcmin;   //  min HC encountered in a round
 static  int numc,numcz; numc = 1;numcz = 1;   //  number of differentials used for HC determination, sliding scale of from 1 (for 3 rounds played), up to 10 for full slate of 20 rounds played
   double diff_corr0, diff_corr;   //  the value of the correction applied to differentials when a sub-zero HC is reset to zero
   int i_zero_flag;   //  flag to indicate that a subzero HC has been detected in this particular round,   ==0 no subzero HC found ;   ==1   subzero HC found, activate corrections
  int id_zfc;  //  player index of low diff_corr value for subZero situation
   	static int rank_hc[n_player];  //  rank of player n's HC
     static int rank_as[90];    //  in round r, rank of nth adjusted score
  
   static int num_win[n_rounds]; string adj_win[n_rounds][6];  //  from data file TOSS_adj_winners.dat::  number of players cashing in nth round;  names of these cashing players in nth round
 int num_cash_rnds; num_cash_rnds = 0;   //  counter used to determine cutoff of number of cashing players in simulated rounds, compared to num_win[n_rounds]
	static int win_count[n_player]; static int sim_win_count[n_player];  // number of times nth player cashed based on real results,  number of times nth player cashed in simulated model 
 
	int quitOrNo;     //  runtime dummy, useful for keeping .exe window open to inpect diagnostic output

// variables to handle multi-sub-scratch anomalies  
static int num_ss;  // number of sub scratch players in this round    ==i_zero_flag
int i_zfc;  // counter index of number of sub-scratch rounds this round 
static int low_ssID ; //  player id of lowest subscratch players in this round
static int  ss_id[10]; static double ss_diff_corr[10] ={0.0};   static double minDC ;
 static int  ss_numc[10];


 //  seed values
// course_rnds[num_crs] icrs_ref[1-5][num_crs] =        most recent round is index==5
//  epw
course_rnds[1] =1;  icrs_ref[1][1] = 59.0;
// epb
course_rnds[2] =5;  icrs_ref[1][2] = 63.4; icrs_ref[2][2] = 61.2; icrs_ref[3][2] = 57.9; icrs_ref[4][2] = 59.0; icrs_ref[5][2] = 62.2;
//epy
course_rnds[3] =5;  icrs_ref[1][3] = 65.2; icrs_ref[2][3] = 64.4; icrs_ref[3][3] = 61.8; icrs_ref[4][3] = 64.0; icrs_ref[5][3] = 65.2;
//eiw
course_rnds[4] =1;  icrs_ref[1][4] = 56.6;
//eib
course_rnds[5] =5;  icrs_ref[1][5] = 56.4;  icrs_ref[2][5] = 52.8; icrs_ref[3][5] = 52.8 ; icrs_ref[4][5] = 54.2 ; icrs_ref[5][5] = 56.2 ;
//eiy
course_rnds[6] =5;  icrs_ref[1][6] = 55.8;   icrs_ref[2][6] = 70.2; icrs_ref[3][6] = 69.6 ; icrs_ref[4][6] = 56.2 ; icrs_ref[5][6] = 56.6 ;
//unq is num_crs 7:  skip for reference seed data
course_rnds[7] =0;
//lmb                       
course_rnds[8] =2;  icrs_ref[1][8] = 53.0;   icrs_ref[2][8] = 56.8;  
//lmy                                                                                
course_rnds[9] =2;  icrs_ref[1][9] = 57.6;   icrs_ref[2][9] = 60.6;  
//  alm0
course_rnds[10] =5;  icrs_ref[1][10] = 52.4;   icrs_ref[2][10] = 52.2; icrs_ref[3][10] = 52.6 ; icrs_ref[4][10] = 53.6 ; icrs_ref[5][10] = 56.6 ;
//kan
course_rnds[11] =5;  icrs_ref[1][11] = 49.6;   icrs_ref[2][11] = 45.8; icrs_ref[3][11] = 51.8 ; icrs_ref[4][11] = 46.0 ; icrs_ref[5][11] = 51.6 ;
//kpv
course_rnds[12] =0;
//mtn
course_rnds[13] =5;  icrs_ref[1][13] = 57.6;   icrs_ref[2][13] = 55.0; icrs_ref[3][13] = 56.6 ; icrs_ref[4][13] = 55.8 ; icrs_ref[5][13] = 54.8 ;
 //cur
course_rnds[14] =0;
//shr                                        
course_rnds[15] =5;     icrs_ref[1][15] = 51.6;   icrs_ref[2][15] = 50.0; icrs_ref[3][15] = 51.8 ; icrs_ref[4][15] = 52.8 ; icrs_ref[5][15] = 52.0 ;
 //upi
course_rnds[16] =0;
 //kvb
course_rnds[17] =0;
 //ffw
course_rnds[18] =0;
 //rhl
course_rnds[19] =0;
 //alm
course_rnds[20] =0;
 //kvr
course_rnds[21] =0;
 //alb
course_rnds[22] =0;
 //aly
course_rnds[23] =0;
 //cf
course_rnds[24] =0;
//kvy
course_rnds[25] = 0;
//alr
course_rnds[26] = 0;
//ctp
course_rnds[27] = 0;
//initialize 
for (int j = 1; j < num_crs; j++) {if(course_rnds[j]>0) {crS=0;crT=0; 	for (int i = 1; i <= course_rnds[j]; ++i) {crS = crS + icrs_ref[i][j];  crT++; }		crs_ref[j] = crS /crT;  }     }
