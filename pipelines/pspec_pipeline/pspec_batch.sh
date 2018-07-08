#!/bin/bash
#PBS -q hera
#PBS -V
#PBS -j oe
#PBS -o pspec_batch.out
#PBS -l nodes=1:ppn=8
#PBS -l walltime=24:00:00
#PBS -l vmem=128gb, mem=128gb

# start script
echo "starting power spectrum pipeline: $(date)"

# put a lock on parameter file, run pspec_pipe.py, unlock file
chmod 444 pspec_pipe.yaml
python pspec_pipe.py pspec_pipe.yaml
chmod 775 pspec_pipe.yaml

# end script
echo "ending power spectrum pipeline: $(date)"
