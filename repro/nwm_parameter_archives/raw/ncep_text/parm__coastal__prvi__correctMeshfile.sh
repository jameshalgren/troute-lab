#!/usr/bin/env bash
module load nco

mv hgrid.nc hgrid-prev.nc
ncap2 -s "elementConn=elementConn+1" hgrid-prev.nc hgrid.nc

mv open_bnds_hgrid.nc open_bnds_hgrid-prev.nc
ncap2 -s "elementConn=elementConn+1" open_bnds_hgrid-prev.nc open_bnds_hgrid.nc
