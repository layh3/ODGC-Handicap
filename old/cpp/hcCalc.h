void hcc(const double, int, double);

double hcc(const double x[], int ir)
{
	double hcc;  hcc=0;     double xhold;    double y[21] = {} ;
	int num;     
  if (ir < 3) num = 0; if (ir>2 && ir<6) num = 1; if (ir>5 && ir<9) num = 2; if (ir>8 && ir<11) num = 3; if (ir>10 && ir<13) num = 4; 
    if (ir>12 && ir<15) num = 5; if (ir>14 && ir<17) num = 6; if (ir==17) num = 7;  if (ir==18) num = 8; if (ir==19) num = 9; if (ir>=20) num = 10;  
//sort(x, x + num);	

  // crappy bubble sort          put differential array into y[], sort, then take the leading NUM elements (according to number of rounds played) to calc HC
	int irmax = min(20, ir);
    for (int j = 1; j <=irmax; j++) y[j] = x[j]; 
 //   for (int j = 1; j <=irmax; j++) cout << " before:sort   j = " << j << " y[j] =  " << y[j] << " ir  =  " << ir << '\n'; 
      
       for (int ij = 1; ij <= irmax -1; ij++)  {    for (int j = 1; j <= irmax - ij ; j++)  {   if(y[j] > y[j+1])  { xhold = y[j]; y[j]=y[j+1]; y[j+1]= xhold; }  }  } 
   
   
 //      for (int j = 1; j < ir-1; j++)  {   if(y[j] > y[j+1])  { xhold = y[j]; y[j]=y[j+1]; y[j+1]= xhold; }  }   
//   for (int j = ir; j > 1; j--)  {   if(y[j] < y[j-1])  { xhold = y[j]; y[j]=y[j-1]; y[j-1]= xhold; }  }
   
//   for (int j = 1; j <=irmax; j++) cout << " arr:after:sort   j = " << j << " y[j] =  " << y[j] << '\n'; 
// for (int j = 1; j <= irmax; j++)my2file << "  ir   = " << irmax << "  num   = " << num << "  j   = " << j << "  y[j]  = " << y[j] << '\n';
	 //   for (int j = 1; j <= num; j++)my2file << "  ir   = " << irmax << "  num   = " << num << "  j   = " << j << "  y[j]  = " << y[j] << '\n';

  	for (int i = 1; i <= num; i++)
	{
		hcc += y[i];
	}
	if (hcc<0) my2file << "  ZERO!  diff_core   = " << hcc/num << '\n';
//	hcc = max(0.0, hcc*0.96 / num);       my2file << "  in hcc routine:ir   = " << irmax << "  num   = " << num << "  new HC  = " << hcc << '\n';
	hcc =  hcc*0.96 / num ;     //  my2file << "  in hcc routine:ir   = " << irmax << "  num   = " << num << "  new HC  = " << hcc << '\n';
	if(hcc<0) my2file << "  ZERO!  hcc   = " << hcc <<  '\n';
  hcc=min(hcc,36.0);
	return hcc;
}
