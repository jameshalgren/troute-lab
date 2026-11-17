#!/usr/bin/env python3
# Standalone quick/dirty program to take input 
# NLDAS climo distribution data for each hour
# of the year, and map the values to the 
# global CFSv2 grid. This is desired for the new 
# forcing engine in Python as having input 
# parameters on the same grid helps out a ton.

# Logan Karsten
# National Center for Atmospheric Research
# Research Applications Laboratory

import datetime
import numpy as np
import sys
from netCDF4 import Dataset
import os

# Establish constants
outDir = '/glade/p/cisl/nwc/karsten/NWM_v21_Dev/INPUT/Forcing_Params/CFSv2_Params/NLDAS_Climo'
inDir = '/glade/p/cisl/nwc/karsten/NWM_v21_Dev/INPUT/Forcing_Params/CFSv2_Params/NLDAS_Climo_ORIG'
corrFile = '/glade/p/cisl/nwc/karsten/NWM_v21_Dev/INPUT/Forcing_Params/CFSv2_Params/NLDAS_Climo_ORIG/nldas_param_cfsv2_subset_grid_correspondence.nc'

begDate = datetime.datetime(2008,1,1)
nSteps = 8784

xstart = 224
xend = 331
ystart = 30
yend = 78

# Create empty NumPy array on CFSv2 grid that will hold output values. 
# Data will be reset to missing values each time. 
gridOut = np.empty([190,384],np.float64)
gridOut[:,:] = -9999.0

# Read in correspondance file and pull out necessary variables.
idCorr = Dataset(corrFile,'r')
grid_lon = idCorr.variables['grid_lon'][:,:]
grid_lat = idCorr.variables['grid_lat'][:,:]
grid_s_lat = idCorr.variables['start_lat'][0]
grid_s_lon = idCorr.variables['start_lon'][0]
grid_e_lat = idCorr.variables['end_lat'][0]
grid_e_lon = idCorr.variables['end_lon'][0]

idCorr.close()

# Read in dummy lat/lon info from a CFS file.
fileDummy = '/glade/p/cisl/nwc/karsten/NWM_v21_Dev/INPUT/Forcing_Params/CFSv2_Params/CFSv2_Climo/cfs_prate_0828_18_dist_params.nc'
idTmp = Dataset(fileDummy,'r')
latDummy = idTmp.variables['lat_0'][:]
lonDummy = idTmp.variables['lon_0'][:]
idTmp.close()

for step in range(0,nSteps):
    # Reset CFS grid to missing values.
    gridOut[:,:] = -9999.0

    dCurrent = begDate + datetime.timedelta(seconds=3600*step)
    
    fileIn = inDir + "/nldas2_" + dCurrent.strftime('%m%d%H') + "_dist_params.nc"
    fileOut = outDir + "/nldas2_" + dCurrent.strftime('%m%d%H') + "_dist_params.nc"

    print('XXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
    print('IN FILE = ' + fileIn)
    print('OUT FILE = ' + fileOut)

    if os.path.isfile(fileOut):
        continue

    if dCurrent.month == 2 and dCurrent.day == 29:
        continue
    # Create cutout - This is based of the archaic/asinine NCL code that is 
    # ran for long range bias correction.
    #print('CREATING SUB-GRIDS')
    gridSub = gridOut[ystart:yend,xstart:xend]

    #print('OPENING INPUT FILE')
    # Open the input NLDAS parameter file
    idIn = Dataset(fileIn,'r')

    #print('OPENING OUTPUT FILE.')
    # Open the ouptut file for writing
    idOut = Dataset(fileOut,'w')
    idOut.createDimension('param')
    idOut.createDimension('lat_0',190)
    idOut.createDimension('lon_0',384)
    
    idOut.createVariable('lat_0','f4',('lat_0'))
    idOut.variables['lat_0'].long_name = 'latitude'
    idOut.variables['lat_0'].grid_type = 'Gaussian Latitude/Longitude'
    idOut.variables['lat_0'].units = 'degrees_north'
    idOut.variables['lat_0'].N = 95.0
    idOut.variables['lat_0'].Di = 0.9374987
    idOut.variables['lat_0'].Lo2 = 359.062
    idOut.variables['lat_0'].La2 = -89.277
    idOut.variables['lat_0'].Lo1 = 0.0
    idOut.variables['lat_0'].La1 = 89.277

    idOut.createVariable('lon_0','f4',('lon_0'))
    idOut.variables['lon_0'].long_name = 'longitude'
    idOut.variables['lon_0'].grid_type = 'Gaussian Latitude/Longitude'
    idOut.variables['lon_0'].units = 'degrees_east'
    idOut.variables['lon_0'].N = 95.0
    idOut.variables['lon_0'].Di = 0.9374987
    idOut.variables['lon_0'].Lo2 = 359.062
    idOut.variables['lon_0'].La2 = -89.277
    idOut.variables['lon_0'].Lo1 = 0.0
    idOut.variables['lon_0'].La1 = 89.277

    idOut.variables['lat_0'][:] = latDummy
    idOut.variables['lon_0'][:] = lonDummy

    varNames = ['UGRD10M_PARAM_1','UGRD10M_PARAM_2','VGRD10M_PARAM_1','VGRD10M_PARAM_2',
                'T2M_PARAM_1','T2M_PARAM_2','Q2M_PARAM_1','Q2M_PARAM_2',
                'PSFC_PARAM_1','PSFC_PARAM_2','LW_PARAM_1','LW_PARAM_2',
                'SW_PARAM_1','SW_PARAM_2','PRATE_PARAM_1','PRATE_PARAM_2',
                'ZERO_PRECIP_PROB']
    for varTmp in varNames:
        #print('PROCESSING: ' + varTmp)
        gridTmp = idIn.variables[varTmp][:,:]

        #print('MAPPING OLD GRID TO NEW GRID.')
        for y in range(grid_s_lat,grid_e_lat):
            for x in range(grid_s_lon,grid_e_lon):
                y_ind = y-grid_s_lat
                x_ind = x-grid_s_lon

                gridSub[y-1,x-1] = gridTmp[grid_lat[y_ind,x_ind],grid_lon[y_ind,x_ind]]

        gridSub[np.where(gridSub > 500000.0)] = -9999.0
        gridSub[np.isnan(gridSub)] = -9999.0
        if varTmp == 'PRATE_PARAM_1' or varTmp == 'PRATE_PARAM_2':
            gridSub[np.where(gridSub == 0.0)] = -9999.0
        if varTmp == "ZERO_PRECIP_PROB":
            gridSub[np.where(gridSub == 0.0)] = -9999.0

        idOut.createVariable(varTmp,'f8',('lat_0','lon_0'),fill_value=-9999.0)
        gridOut[ystart:yend,xstart:xend] = gridSub
        idOut.variables[varTmp][:,:] = gridOut

        gridOut[:,:] = -9999.0
        gridSub[:,:] = -9999.0
                    
              
    idIn.close()
    idOut.close()
