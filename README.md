# reqmgr2cwl — ReqMgr2 → CWL translation pipeline

Translates CMS **ReqMgr2** `TaskChain`/`StepChain` request JSON
documents into runnable **CWL v1.2** workflows, wires up a Github Workflow Actions
pipeline around the translation, and (optionally) executes the result
with `cwltool`.

## How it works

### 1. What's actually in a ReqMgr2 request
A `TaskChain` request (example_request.json) describes a chain of CMSSW
processing steps as `Task1`, `Task2`, ... `TaskN`. Each task carries:

- `CMSSWVersion` / `ScramArch` — which CMSSW release + platform to run
- `GlobalTag` — the conditions/calibration tag
- `InputDataset` (consumes the previous step's dataset) **or**
  `PrimaryDataset` (first task, generates events from scratch)
- `Memory`, `Multicore` — per-task resource needs
- `ConfigCacheID` — a pointer to the *real* cmsRun pset (Python config),
  which lives in a separate CouchDB document at `ConfigCacheUrl`, **not**
  inside this JSON
- `ChainParentageMap` — how each task's output dataset feeds the next
  task's input

This JSON is a **request/bookkeeping record**,
not a self-contained job description. The actual executable config
(the cmsRun pset) must be fetched separately in the real CMS submission
system. The translator can't invent that file, so it wires a `File`
input slot for it and records exactly where to fetch it from.

### 2. The translation (`reqmgr2cwl/translator.py`)
For each `TaskN`/`StepN`:
- Emits one CWL **CommandLineTool** (`tools/TaskN.cwl`) with:
  - `hints.DockerRequirement` → a CMSSW container image derived from
    `CMSSWVersion`/`ScramArch` (a *hint*, not a hard `requirement`, so
    the workflow can still be validated/dry-run with `cwltool
    --no-container` on runners without Docker/CVMFS)
  - `requirements.ResourceRequirement` → `coresMin`/`ramMin` from
    `Multicore`/`Memory`
  - inputs for `cmsswVersion`, `globalTag`, `configFile` (the pset,
    staged externally), `nEvents`, and if the task has a parent —
    `inputFile`
  - a single `outputFile` output
- Chains tasks into a top-level **Workflow** (`workflow.cwl`), wiring
  `TaskN/outputFile → TaskN+1/inputFile` according to
  `ChainParentageMap`, using the same ordering ReqMgr2 uses (`Task1`
  feeds `Task2`, etc.)
- Emits a `job.yml` skeleton listing each task's `configFile` input
  with a `doc:` comment pointing at the CouchDB URL/ID to fetch the
  real pset from

### 3. "Run that CWL workflow" — To Be Done

- **What genuinely runs, anywhere:** the CWL workflow is syntactically
  valid, `cwltool` schedules and executes each step in the correct
  order, resources/parameters flow correctly, and `finalOutput` is
  produced — verified locally in this sandbox end-to-end.
- **What's stubbed:** `scripts/cmsRun_wrapper.sh` is a placeholder for
  the real `cmsRun` invocation. Real execution needs:
  1. The actual pset fetched from
     `ConfigCacheUrl/<CouchDBName>/<ConfigCacheID>` (CouchDB
     attachment, requires a CERN-authenticated client) placed at the
     path `job.yml` expects.
  2. Either a CMSSW Docker/Singularity image with CVMFS bind-mounted
     in, or a runner that has CVMFS + a valid grid proxy natively.
  3. `dockerPull` in each `tools/TaskN.cwl` pointed at an image that
     actually exists in your registry — `registry.cern.ch/...` in the
     generated file is illustrative; substitute your site's mirror.

  Swap the body of `cmsRun_wrapper.sh` for the real `cmsRun` call (see
  the comment block at the top of that file) once you're running on
  infrastructure that has CVMFS/the CMSSW releases available, and the
  same `workflow.cwl` will execute the real jobs — nothing about the
  CWL graph itself needs to change.

## Running in GitHub Actions

The workflow definition lives at `.github/workflows/reqmgr2cwl.yml` —
note this is a *different* `workflows/` than the top-level `workflows/`
folder in this repo, which holds the ReqMgr2 request JSON files being
translated. GitHub requires workflow YAML specifically under
`.github/workflows/`; there's no naming conflict, just to clarify.

Jobs mirror the four pipeline stages: `validate → translate → lint →
run_cwl`.

- **validate / translate / lint** run automatically on every push or
  PR that touches `workflows/**.json`, `reqmgr2cwl/**`, `ci/**`, or
  `scripts/**`.
- **run_cwl** does **not** run automatically. GitHub Actions has no
  direct equivalent of GitLab's `when: manual`, so it's gated behind a
  manual trigger instead:
  - Go to **Actions → reqmgr2cwl → Run workflow**
  - Set `reqmgr2_json` to the request you want (defaults to
    `workflows/example_request.json`)
  - Set `run_execution` to `true`
  - Run — this downloads the `cwl-output` artifact from the
    `translate` job, stages placeholder psets, and executes
    `cwltool --no-container`, then uploads a `cwl-results` artifact.

If you want an actual approval gate (someone has to click "approve")
rather than just a checkbox at dispatch time, add
`environment: cwl-run` to the `run_cwl` job and configure required
reviewers under **Settings → Environments → New environment**.

## Repo layout
```
reqmgr2cwl/translator.py   # JSON -> CWL translator
ci/validate_reqmgr2.py     # pre-flight schema/field check
scripts/cmsRun_wrapper.sh  # container entrypoint (stub; swap for real cmsRun)
workflows/example_request.json
.github/workflows/reqmgr2cwl.yml
```

## Running locally
```bash
pip install pyyaml cwltool

# 1. validate
python ci/validate_reqmgr2.py workflows/example_request.json

# 2. translate
python reqmgr2cwl/translator.py workflows/example_request.json cwl_output

# 3. lint
cwltool --validate cwl_output/workflow.cwl

# 4. run (stub cmsRun, no Docker needed)
cp scripts/cmsRun_wrapper.sh cwl_output/
chmod +x cwl_output/cmsRun_wrapper.sh
export PATH="$PWD/cwl_output:$PATH"
mkdir -p cwl_output/configs
echo "# placeholder pset" > cwl_output/configs/Task1_config.py
cd cwl_output && cwltool --no-container --outdir ../results workflow.cwl job.yml
```
This is exactly what the pipeline's four stages do in CI.

## Extending
- **StepChain** requests are handled by the same code path (`Task` ↔
  `Step` prefix is auto-detected).
- **Fetching real configs automatically**: add a stage between
  `translate_to_cwl` and `lint_cwl` that does, per task,
  `curl -u "$CERN_USER:$CERN_PASS" "$ConfigCacheUrl/$CouchDBName/$ConfigCacheID/configFile"`
  and writes it to the path `job.yml` expects — store CERN credentials
  as protected/masked GitLab CI variables.
- **Multi-task chains**: no changes needed — the parentage wiring
  already generalizes to `TaskChain: N` for any `N`.
