#!/bin/bash
#SBATCH -c 10 --constraint=amd --array=0-XXXX -t 1:00:00

#MSLIST TEXT FILE WITH PATH TO MS
MSLIST=$1

#SCRIPT FOLDER
SCRIPT_DIR=/home/lofarvwf-jdejong/scripts/lofar_helpers/phasediff_scores/phasediff_selection

#SINGULARITY
BIND=$( python3 $HOME/parse_settings.py --BIND ) # SEE --> https://github.com/jurjen93/lofar_vlbi_helpers/blob/main/parse_settings.py
SIMG=$( python3 $HOME/parse_settings.py --SIMG )

#phasediff output folder
mkdir -p phasediff_h5s

IFS=$'\r\n' GLOBIGNORE='*' command eval  'MSS=($(cat ${MSLIST}))'
MS=$MSS[${SLURM_ARRAY_TASK_ID}]

#RUN MS FROM MS LIST
mkdir ${MS}_folder
mv ${MS} ${MS}_folder
cd ${MS}_folder
singularity exec -B $BIND $SIMG ${SCRIPT_DIR}/phasediff.sh ${MS}
mv scalarphasediff0*phaseup.h5 ../phasediff_h5s
mv ${MS} ../
cd ../
rm -rf ${MS}_folder

#RETURN SCORES
singularity exec -B $BIND $SIMG python ${SCRIPT_DIR}/phasediff_output.py --h5 phasediff_h5s/*.h5
