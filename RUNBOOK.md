# SpecForge Runbook

The main operations runbook lives in [docs/RUNBOOK.md](docs/RUNBOOK.md). This
root runbook records cross-repository workflows that are referenced by CI
contracts.

## 10. Prompt Pipeline Experimentation Workflow

### 10.1 When to run the eval suite

- Any structural change to a stage prompt, including a new mandatory section or
  a changed verification checklist.
- Any change to the critic prompt template in `services/pipeline/critic.py`.
- Any change to `SECTION_CONTRACTS` in `artifact_validator.py`.

### 10.2 Workflow

1. Create a branch off `main`.
2. Edit the prompt file.
3. Bump `ASDD_PROMPT_VERSION` in `backend/prompts/base.py:12`; use a minor bump
   for structural changes and a patch bump for wording changes.
4. Run the eval locally:

   ```bash
   cd harness && uv run python -m prompt_eval.run \
     --version <new> --baseline <old> --report report.md
   ```

5. Review `report.md`. Per-grader pass-rate must be greater than or equal to
   baseline; any regression must be justified before merge.
6. Open the PR. CI runs the eval automatically and posts the report as a sticky
   comment.
7. Re-baseline once a quarter.

### 10.3 Quarterly re-baseline

Every quarter, replace one golden workspace with a new anonymized workspace that
reflects the current product surface area. Run the eval on `main` and save the
new `baseline_scores.json` files. This keeps the prompt_eval suite meaningful as
the product changes.
