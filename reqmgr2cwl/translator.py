#!/usr/bin/env python3
"""
translator.py

Converts a CMS ReqMgr2 (WMCore) request document — TaskChain or StepChain —
into a CWL v1.2 Workflow: one CommandLineTool per Task/Step, wired together
according to ChainParentageMap, plus a job input skeleton (job.yml).

ReqMgr2 background (for maintainers):
  A TaskChain request describes a chain of CMSSW processing steps
  (Task1, Task2, ... TaskN). Each task carries its own CMSSW release,
  global tag, per-task resource needs, and either an InputDataset (it
  consumes the previous task's output) or a PrimaryDataset (it's the
  first task, generating events from scratch). The real per-task
  CMSSW configuration (cmsRun pset) is NOT embedded in this JSON — it's
  stored separately in a CouchDB "ConfigCache" document referenced by
  ConfigCacheID, fetched from ConfigCacheUrl. This translator does not
  and cannot fabricate that pset; it emits a CWL input slot for it and
  documents where to fetch it from.

Usage:
    python translator.py <input.json> <output_dir>

Output layout:
    <output_dir>/workflow.cwl      - top-level CWL Workflow
    <output_dir>/tools/<Task>.cwl  - one CommandLineTool per task/step
    <output_dir>/job.yml           - job input skeleton (paths need filling in)
"""
import json
import os
import sys

import yaml


def sanitize(name: str) -> str:
    """CWL identifiers must be alphanumeric/underscore."""
    out = "".join(c if c.isalnum() else "_" for c in str(name))
    out = out.strip("_")
    return out or "task"


def collect_tasks(spec: dict):
    """Return an ordered list of (task_key, task_dict) for Task1..N or Step1..N."""
    if "TaskChain" in spec:
        n, prefix = spec["TaskChain"], "Task"
    elif "StepChain" in spec:
        n, prefix = spec["StepChain"], "Step"
    else:
        return []
    tasks = []
    for i in range(1, int(n) + 1):
        key = f"{prefix}{i}"
        if key in spec:
            tasks.append((key, spec[key]))
    return tasks


def docker_image_for(cmssw: str, scram_arch: str) -> str:
    """
    Map a CMSSW release + SCRAM arch to a container image reference.
    CMS publishes official CMSSW release containers under this pattern;
    adjust the registry to whatever your site mirrors/hosts internally.
    """
    return f"registry.cern.ch/cms-cloud/{scram_arch}:{cmssw}"


def build_commandlinetool(task_key: str, task: dict, spec: dict) -> dict:
    """Build a CWL CommandLineTool describing one ReqMgr2 task."""
    cmssw = task.get("CMSSWVersion", spec.get("CMSSWVersion"))
    scram_arch = task.get("ScramArch", spec.get("ScramArch", ["el8_amd64_gcc12"]))
    scram_arch = scram_arch[0] if isinstance(scram_arch, list) else scram_arch
    global_tag = task.get("GlobalTag", spec.get("GlobalTag"))
    memory_mb = task.get("Memory", spec.get("Memory", 2000))
    cores = task.get("Multicore", spec.get("Multicore", 1))
    config_cache_id = task.get("ConfigCacheID")
    config_cache_url = spec.get("ConfigCacheUrl")
    input_dataset = task.get("InputDataset")
    primary_dataset = task.get("PrimaryDataset")
    events_per_job = task.get("EventsPerJob")

    inputs = {
        "cmsswVersion": {
            "type": "string",
            "default": cmssw,
            "inputBinding": {"prefix": "--cmssw-version"},
        },
        "globalTag": {
            "type": "string",
            "default": global_tag,
            "inputBinding": {"prefix": "--global-tag"},
        },
        # The actual cmsRun pset python file, fetched ahead of time from
        # ConfigCacheUrl/ConfigCacheID (see README) and staged as a File input.
        "configFile": {
            "type": "File",
            "doc": (
                f"cmsRun pset fetched from {config_cache_url} "
                f"(ConfigCacheID={config_cache_id})"
            ),
            "inputBinding": {"prefix": "--config"},
        },
        "nEvents": {
            "type": ["null", "int"],
            "default": events_per_job if events_per_job else -1,
            "inputBinding": {"prefix": "--n-events"},
        },
    }
    if input_dataset:
        inputs["inputFile"] = {
            "type": ["null", "File"],
            "doc": f"Output staged from the parent task (dataset: {input_dataset})",
            "inputBinding": {"prefix": "--input-file"},
        }
    if primary_dataset:
        inputs["primaryDataset"] = {
            "type": "string",
            "default": primary_dataset,
            "inputBinding": {"prefix": "--primary-dataset"},
        }

    tool = {
        "cwlVersion": "v1.2",
        "class": "CommandLineTool",
        "id": sanitize(task_key),
        "label": task.get("TaskName", task_key),
        "doc": f"CMSSW task '{task_key}' translated from ReqMgr2 request "
               f"{spec.get('RequestName', spec.get('_id', ''))}.",
        "requirements": {
            "ResourceRequirement": {"coresMin": cores, "ramMin": memory_mb},
            "InlineJavascriptRequirement": {},
        },
        "hints": {
            "DockerRequirement": {"dockerPull": docker_image_for(cmssw, scram_arch)},
        },
        "baseCommand": ["cmsRun_wrapper.sh"],
        "inputs": inputs,
        "outputs": {
            "outputFile": {"type": "File", "outputBinding": {"glob": "output.root"}},
        },
    }
    return tool


def build_workflow(spec: dict, tasks) -> dict:
    parentage = spec.get("ChainParentageMap", {})
    steps = {}
    prev_step_id = None

    for task_key, task in tasks:
        step_id = sanitize(task_key)
        step_in = {"configFile": f"{step_id}_config"}

        parent_info = parentage.get(task_key, {})
        # A task with a recorded ParentDset that isn't itself the first
        # task consumes the previous step's output file.
        if prev_step_id and parent_info.get("ParentDset") and task.get("InputDataset"):
            step_in["inputFile"] = f"{prev_step_id}/outputFile"

        steps[step_id] = {
            "run": f"tools/{step_id}.cwl",
            "in": step_in,
            "out": ["outputFile"],
        }
        prev_step_id = step_id

    workflow_inputs = {
        f"{sanitize(k)}_config": "File" for k, _ in tasks
    }

    workflow = {
        "cwlVersion": "v1.2",
        "class": "Workflow",
        "id": sanitize(spec.get("RequestName", "reqmgr2_workflow")),
        "label": spec.get("RequestName", "reqmgr2_workflow"),
        "doc": f"Auto-generated from ReqMgr2 request "
               f"{spec.get('RequestName', spec.get('_id', ''))} "
               f"(RequestType={spec.get('RequestType')}).",
        "requirements": {"SubworkflowFeatureRequirement": {}},
        "inputs": workflow_inputs,
        "steps": steps,
        "outputs": {},
    }

    if tasks:
        last_id = sanitize(tasks[-1][0])
        out_dataset = None
        if spec.get("OutputDatasets"):
            out_dataset = spec["OutputDatasets"][-1]
        workflow["outputs"]["finalOutput"] = {
            "type": "File",
            "outputSource": f"{last_id}/outputFile",
            "doc": f"Corresponds to CMS dataset: {out_dataset}" if out_dataset else None,
        }

    return workflow


def build_job_skeleton(spec: dict, tasks) -> dict:
    job = {}
    for task_key, task in tasks:
        step_id = sanitize(task_key)
        job[f"{step_id}_config"] = {
            "class": "File",
            "path": f"configs/{step_id}_config.py",
            "doc": (
                f"REPLACE with the pset fetched from "
                f"{spec.get('ConfigCacheUrl')}/{spec.get('CouchDBName', 'reqmgr_config_cache')}"
                f"/{task.get('ConfigCacheID')}"
            ),
        }
    return job


def translate(infile: str, outdir: str):
    with open(infile) as f:
        spec = json.load(f)

    tasks = collect_tasks(spec)
    if not tasks:
        raise ValueError(
            "Input does not look like a TaskChain/StepChain request "
            "(no TaskChain/StepChain key or no TaskN/StepN found)."
        )

    tools_dir = os.path.join(outdir, "tools")
    os.makedirs(tools_dir, exist_ok=True)

    for task_key, task in tasks:
        tool = build_commandlinetool(task_key, task, spec)
        with open(os.path.join(tools_dir, f"{sanitize(task_key)}.cwl"), "w") as f:
            f.write("#!/usr/bin/env cwl-runner\n")
            yaml.dump(tool, f, sort_keys=False, default_flow_style=False)

    workflow = build_workflow(spec, tasks)
    with open(os.path.join(outdir, "workflow.cwl"), "w") as f:
        f.write("#!/usr/bin/env cwl-runner\n")
        yaml.dump(workflow, f, sort_keys=False, default_flow_style=False)

    job = build_job_skeleton(spec, tasks)
    with open(os.path.join(outdir, "job.yml"), "w") as f:
        yaml.dump(job, f, sort_keys=False, default_flow_style=False)

    return tasks


def main():
    if len(sys.argv) != 3:
        print("usage: translator.py <input.json> <output_dir>", file=sys.stderr)
        sys.exit(1)
    infile, outdir = sys.argv[1], sys.argv[2]
    try:
        tasks = translate(infile, outdir)
    except Exception as exc:
        print(f"translation failed: {exc}", file=sys.stderr)
        sys.exit(2)
    print(f"Wrote workflow.cwl, job.yml, and {len(tasks)} tool(s) under {outdir}/")


if __name__ == "__main__":
    main()
