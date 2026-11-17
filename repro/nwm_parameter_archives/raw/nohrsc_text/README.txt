Current NWM parameter files
---------------------------
 * Applies to NWM v2.0, starting 2019-06-19.
 * This file list and description also applies to previous versions of the
   NWM, but file contents may differ between versions.

* Fulldom_hires_netcdf_1km.nc.gz
File description:  This file contains gridded physiographic and model parameter
data for the 'Long-range' configuration of the National Water Model.

* Fulldom_hires_netcdf_250m.nc.gz
File description:  This file contains gridded physiographic and model parameter
data for the 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
configurations of the National Water Model.

* RouteLink_NHDPLUS.nc.gz
File description:  This file contains river channel definition and parameter
data, and USGS stream gauge river reach definitions used in all configurations
of the National Water Model.

* spatialweights_1km_all_basins.nc.gz
File description:  This file contains the spatial regridding weights, used to
map variables from the 1km WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Long Range' configuration of the National Water Model.

* spatialweights_250m_all_basins.nc.gz
File description:  This file contains the spatial regridding weights, used to
map variables from the 250m WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Analysis and Assimilation', 'Short Range' and 'Medium
Range' configurations of the National Water Model.

* LAKEPARM_NHDPLUS.nc
File description: Provides the static parameters that describe the initial
fullness, size (in terms of surface area and maximum elevation), and discharge
mechanisms (orifice and weir) for each NWM waterbody. The lake_id corresponds
with the NHD+WaterbodyComID

* nudgingParams.nc 
File description: Channel_rt nudge parameters. Supplies the parameters for the
application of streamflow nudging data assimilation within the model
