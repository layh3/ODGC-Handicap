void stdev(const double, double, int);

double stdev(const double x[], double mean, int size)
{
	double stdev;
	double sum2; sum2 = 0;
	
//	my2file << " x_1  " << x[1] << " x_last  " << x[size] << " size  " << size << '\n';  
//	for (int j = 1; j <=  size; j++)  my2file << "in stdev:: x["   << j << "] =   " << x[j] <<   '\n';
  
	for (int i = 1; i <= size; i++)
	{
		sum2 += pow((x[i] - mean), 2);
	}
	stdev = sqrt(sum2 / (size - 1));     //  my2file << " in stdev routine :: stdev   " << stdev << '\n';  
	return stdev;
}
