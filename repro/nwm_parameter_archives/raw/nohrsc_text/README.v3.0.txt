Parameter Description Document for 1) NWM Model and 2) NWM Coastal Module Parameters


1) Current NWM v3.0 parameter files
---------------------------
 * "DOMAIN" below can be:  
 *   CONUS, AK, PRVI or HI for Continental United States, 
 *   Alaska, Puerto Rico / US Virgin ISlands, and Hawaii domains


* Fulldom_CONUS_LongRange.nc
File description:  This file contains gridded physiographic and model parameter
data for the 'Long-range' and 'Long-Range Analysis', configurations of the National Water Model (only for CONUS).


* Fulldom_DOMAIN_FullRouting.nc
File description:  This file contains gridded physiographic and model parameter
data for the 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
configurations of the National Water Model.


* LAKEPARM_DOMAIN.nc
File description: Provides the static parameters that describe the initial
fullness, size (in terms of surface area and maximum elevation), and discharge
mechanisms (orifice and weir) for each NWM waterbody. The lake_id corresponds
with the NHD+WaterbodyComID


* nudgingParams_DOMAIN.nc 
File description: Channel_rt nudge parameters. Supplies the parameters for the
application of streamflow nudging data assimilation within the model


* RouteLink_DOMAIN.nc
File description:  This file contains river channel definition and parameter
data, and USGS stream gauge river reach definitions used in all configurations
of the National Water Model.


* spatialweights_CONUS_LongRange.nc
File description:  This file contains the spatial regridding weights, used to
map variables from the 1km WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Long Range' and 'Long Range Analysis' configurations of the National Water Model.


* spatialweights_DOMAIN_FullRouting.nc
File description:  This file contains the spatial regridding weights, used to
map variables from the 100m/250m WRF-Hydro model grids to the NHDPlusv2 catchment
objects used in the 'Analysis and Assimilation', 'Short Range' and 'Medium
Range' configurations of the National Water Model.


 


2) Current NWM v3.0 Coastal Module (SCHISM) parameter files
---------------------------
* All files are available for the Atlantic Gulf, Pacific, Hawaii and Puerto Rico / US VI domains.


Files:


* bctides.in: Boundary condition input file with horizontal boundary condition and nudging options.
* element_areas.txt:  list of the elements on the SCHISM grids and their corresponding areas in m^2
* elev.ic: A .gr3 format file that specifies the initial elevation at each node.
* elevation_correction.csv: conversion from MSL to NAVD88 for the open boundary nodes on the Pacific and Atlantic domain SCHISM grids
* hgrid.gr3 and hgrid.ll:  Horizontal grid file with node centered spatial data and mesh connectivity
* hgrid.cpp and hgrid.utm: Horizontal grid files in cartesian and UTM coordinates for generating discharge files.
* hgrid.nc: grid file in netcdf format, containing a list of nodes with their locations and elevations along with a list of elements
* hgrid.vtk:  ASCII version of the grid file containing element number, element coordinates, and element original coordinates
* manning.gr3: Bottom friction input file
* nwmReaches.csv: List of the National Water Model Reach IDs which intersect the SCHISM model domain
* open_bnds_hgrid.nc: list of the open boundary nodes and their locations in netcdf format
* param.nml : Main parameter input file 
* vgrid.in: Vertical grid input file
* windrot_geo2proj.gr3: A .gr3 format file contains map projection information for atmospheric forcing files
* Ocean_Land_Mask*.nc: Land-ocean mask files
* k1.nc, k2.nc, m2.nc, n2.nc, o1.nc, p1.nc, q1.nc and S2.nc: Tidal constituents
* sflux_inputs.txt: ASCII file that contains a namelist for atmospheric forcing