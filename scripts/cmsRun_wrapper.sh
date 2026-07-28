#!/usr/bin/env bash
# cmsRun_wrapper.sh
#
# Entry point invoked by every generated CWL CommandLineTool step.
# In a real CMSSW container (with CVMFS mounted and /cvmfs/cms.cern.ch/cmsset_default.sh
# sourced) this becomes:
#
#   source /cvmfs/cms.cern.ch/cmsset_default.sh
#   scramv1 project CMSSW "$CMSSW_VERSION"
#   cd "$CMSSW_VERSION/src" && eval $(scramv1 runtime -sh)
#   cmsRun "$CONFIG_FILE" \
#       inputFiles="$INPUT_FILE" \
#       maxEvents="$N_EVENTS" \
#       globalTag="$GLOBAL_TAG" \
#       output=output.root
#
# This stub instead just logs what it *would* run and produces a
# placeholder output.root, so the pipeline can be exercised (validated,
# dry-run, artifact-checked) on any generic runner that doesn't have
# CVMFS or a CMS grid proxy available — e.g. a shared GitLab runner.
set -euo pipefail

CMSSW_VERSION=""
GLOBAL_TAG=""
CONFIG_FILE=""
N_EVENTS=""
INPUT_FILE=""
PRIMARY_DATASET=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cmssw-version) CMSSW_VERSION="$2"; shift 2 ;;
    --global-tag) GLOBAL_TAG="$2"; shift 2 ;;
    --config) CONFIG_FILE="$2"; shift 2 ;;
    --n-events) N_EVENTS="$2"; shift 2 ;;
    --input-file) INPUT_FILE="$2"; shift 2 ;;
    --primary-dataset) PRIMARY_DATASET="$2"; shift 2 ;;
    *) echo "cmsRun_wrapper.sh: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

echo "== cmsRun_wrapper.sh (stub) =="
echo "CMSSW_VERSION   = $CMSSW_VERSION"
echo "GLOBAL_TAG      = $GLOBAL_TAG"
echo "CONFIG_FILE     = $CONFIG_FILE"
echo "N_EVENTS        = $N_EVENTS"
echo "INPUT_FILE      = ${INPUT_FILE:-<none, first task in chain>}"
echo "PRIMARY_DATASET = ${PRIMARY_DATASET:-<none>}"

if [[ -n "$CONFIG_FILE" && ! -f "$CONFIG_FILE" ]]; then
  echo "ERROR: config file '$CONFIG_FILE' not found" >&2
  exit 1
fi

echo "STUB: would now run: cmsRun $CONFIG_FILE ... (replace this block with real cmsRun in production)"
: > output.root
echo "wrote output.root"
