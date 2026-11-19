# Module: Data pipelines (DVC stage graph + dataset versioning)

Load when a project has two or more data pipelines, or any raw pull or processed build
that is rerun on a schedule. A single pull script with one build behind it needs only
core rules 4, 7 and 8. Airflow, Dagster, Prefect and the like are out of scope: they add
a scheduler service, a database and a UI for problems a one-machine research project
does not have. The tool here is DVC, used narrowly, on top of the layout core already
prescribes.

## What it solves

Core rule 8 puts every scheduled or shared step in `src/` or `scripts/`. It does not say
in what order they run or what depends on what; after a dozen `pull_*` / `build_*`
scripts that order lives in memory. DVC records the graph and reruns only what changed.

```
 dvc.yaml            the MAP: stage = one script, its deps, its outs      ← the pipeline order
 dvc.lock            content hash of every dep and out at the last run
 <dataset>/v<N>.dvc  pointer file per raw dataset version
 ───────────────────────────────────────────────────────────────────────
 scripts/            thin CLIs, one per stage; run by hand without DVC
 src/<package>/      the logic; nothing here knows DVC exists
```

Delete `dvc.yaml`, `dvc.lock`, the pointers and `.dvc/` and the project is exactly as
before: no script depends on the tool. That is the property to preserve.

## Rules

1. **Raw datasets are added, derived data are stage outputs.** `data/raw/<name>/v<N>/`
   gets one `dvc add` per version; the pointer `v<N>.dvc` is committed and the pull
   script stays outside the graph (core rule 7: raw is immutable, so a repro must never
   re-pull). `data/processed/<name>/` and `data/experiments/exp_NN_*/run_<K>/` are
   `outs:` of stages whose `cmd:` is the `build_*` script or the experiment script.
   `frozen:` stages are not used; a pull runs by hand or by a timer, never by repro.
2. **One stage per script, added in the same commit as the script.** A script without a
   stage is the gap `maestro docs check` cannot see; the reviewer must. The stage's
   `deps:` list every input the script reads, including the `src/<package>/<layer>`
   directory whose code it runs, so a code change reruns the stage.
3. **The ignore rule.** Core's template ignores `data/` wholesale, which would swallow
   the pointer files. A DVC project uses instead:
   ```
   data/**
   !data/**/
   !data/**/*.dvc
   !data/**/.gitignore
   ```
   Every data file stays out of git; only the pointers and DVC's own ignore entries go in.
4. **Cache and remote.** Outputs are cached (`cache: true`, the default) so that
   `git checkout <commit> && dvc checkout` restores the data a record was computed from.
   The default remote is whatever object store the machine already runs (an S3-type
   store such as MinIO: `dvc remote add -d <name> s3://<bucket>/dvc` plus
   `dvc remote modify <name> endpointurl http://<host>:9000`, credentials via
   `dvc remote modify --local`, which lands in the gitignored `.dvc/config.local`),
   else a directory on a shared disk. A cloud bucket of the SAME name, checked free
   before the local bucket is created, can be a second remote for the off-site copy
   (`dvc push -r <cloud>`); with identical names the default is moved to the cloud by
   changing the endpoint, nothing else. A very large raw set (tick recordings) may set
   `cache: false` and rely on its manifest; that choice is written in its dataset record.
5. **Maestro records stay the description, DVC stays the dependency.** The `docs/data/`
   record and the manifest say what a dataset is and where it came from; `dvc.lock` says
   what depends on it and whether it changed. An experiment stage does not replace core
   rule 4: the script still writes `params.json`, `run.log` and `metrics.json` itself,
   and the record is still written through the CLI. Tracker setting is unaffected.
6. **`dvc` is a dev dependency of the project** (`uv add --optional dev dvc`), stage
   commands use the project's own interpreter (`uv run python -u scripts/...`), and
   `.dvc/config` is committed; `.dvc/cache` and `.dvc/tmp` are not.

## Day to day

```
 changed src/<layer>/          →  dvc repro                only downstream stages run
 new raw version pulled        →  dvc add data/raw/<name>/v<N>; git add the pointer
 what is the pipeline?         →  dvc dag
 what did the last run use?    →  git show <commit>:dvc.lock
 run one stage without DVC     →  uv run python -u scripts/build_<name>.py   (as before)
 scheduled rebuild             →  timer runs the pull script, then dvc repro <stage>
 adopting an existing project  →  dvc add each raw version; declare stages for the existing
                                  builds and experiments; dvc commit (hashes, no rerun)
```

## Not this module

Run tracking (W&B/MLflow) is `modules/provenance.md`; DVC's own experiment tracking
(`dvc exp`) is not used, the experiment record is. Choosing what a stage computes is
`modules/code.md`.
