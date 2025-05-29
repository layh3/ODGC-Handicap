void leastSqrRegression(const double x[], double y[], int dataSize, double &Rsqr, double &slope, double &y_intercept)
{
	

	double SUMx = 0;     //sum of x values
	double SUMy = 0;     //sum of y values
	double SUMxy = 0;    //sum of x * y
	double SUMxx = 0;    //sum of x^2
	double SUMres = 0;   //sum of squared residue
	double res = 0;      //residue squared
	 slope = 0;    //slope of regression line
	 y_intercept = 0; //y intercept of regression line
	double SUM_Yres = 0; //sum of squared of the discrepancies
	double AVGy = 0;     //mean of y
	double AVGx = 0;     //mean of x
	double Yres = 0;     //squared of the discrepancies
	 Rsqr = 0;     //coefficient of determination

						 //calculate various sums 
	for (int i = 1; i <= dataSize; i++)
	{
		//sum of x
		SUMx = SUMx + x[i];
		//sum of y
		SUMy = SUMy + y[i];
		//sum of squared x*y
		SUMxy = SUMxy + x[i]*y[i];
		//sum of squared x
		SUMxx = SUMxx + x[i]*x[i];
	}

	//calculate the means of x and y
	AVGy = SUMy / dataSize;
	AVGx = SUMx / dataSize;

	//slope or a1
	slope = (dataSize * SUMxy - SUMx * SUMy) / (dataSize * SUMxx - SUMx * SUMx);

	//y itercept or a0
	y_intercept = AVGy - slope * AVGx;

// printf("x mean(AVGx) = %0.5E\n", AVGx); printf("y mean(AVGy) = %0.5E\n", AVGy);
// 
// printf("\n"); printf("The linear equation that best fits the given data:\n"); 
// printf(" y = %2.8lfx + %2.8f\n", slope, y_intercept); 
// printf("------------------------------------------------------------\n"); 
// printf(" Original (x,y) (y_i - y_avg)^2 (y_i - a_o - a_1*x_i)^2\n"); 
// printf("------------------------------------------------------------\n");

	//calculate squared residues, their sum etc.
	for (int i = 1; i <= dataSize; i++)
	{
		//current (y_i - a0 - a1 * x_i)^2
		Yres = pow(y[i] - y_intercept - slope * x[i], 2);

		//sum of (y_i - a0 - a1 * x_i)^2
		SUM_Yres += Yres;

		//current residue squared (y_i - AVGy)^2
		res = pow(y[i] - AVGy, 2);

		//sum of squared residues
		SUMres += res;

//		printf("   (%0.2f %0.2f)      %0.5E         %0.5E\n",x[i], y[i], res, Yres);
	}

	//calculate r^2 coefficient of determination
	Rsqr = (SUMres - SUM_Yres) / SUMres;

// 	printf("--------------------------------------------------\n");
// 	printf("Sum of (y_i - y_avg)^2 = %0.5E\t\n", SUMres);
// 	printf("Sum of (y_i - a_o - a_1*x_i)^2 = %0.5E\t\n", SUM_Yres);
// 	printf("Standard deviation(St) = %0.5E\n", sqrt(SUMres / (dataSize - 1)));
// 	printf("Standard error of the estimate(Sr) = %0.5E\t\n", sqrt(SUM_Yres / (dataSize - 2)));
// 	printf("Coefficent of determination(r^2) = %0.5E\t\n", (SUMres - SUM_Yres) / SUMres);
// 	printf("Correlation coefficient(r) = %0.5E\t\n", sqrt(Rsqr));

}
