# Bounded automatic Hermes repairs

This workflow is prepared but disabled until the repository variable below is
set. It runs on a GitHub-hosted macOS runner (not the user's Mac or Render web
service) at approximately 22:20 Asia/Seoul. GitHub schedules can be delayed.
The existing 08:00/21:00/22:00 Hermes jobs have NOT been migrated by this workflow.

## Activation

In `nabangeeee/Japanese_Chat` → Settings → Secrets and variables → Actions:

1. Add repository secret `NIHONGO_REPAIR_OPENAI_API_KEY`. Use a separate OpenAI
   project key for this worker. Never commit it or put it into a repository variable.
2. After reviewing this policy, add repository variable `NIHONGO_AUTO_REPAIR=true`.
3. Actions → Bounded Hermes automatic repair → Run workflow. Inspect the result.
   A completed end-to-end cloud run is required before claiming activation works.
4. Render must have On Commit enabled for `main`. Its public URL is fixed to
   `https://japanese-chat.onrender.com`. `/api/auth/status` must report the deployed
   `RENDER_GIT_COMMIT` revision before repairs can start.
5. If branch protection refuses direct updates, leave it enabled and use a human
   review flow; do not disable branch protection just to make automation succeed.

Set `NIHONGO_AUTO_REPAIR=false` to stop future jobs. Cancel a running workflow
separately. The GitHub token grants only this repository contents-write and
Actions-read; the agent receives neither it nor the OpenAI key.

## Limits and checks

- One workflow attempt per Korean calendar day, no manual reruns that day.
- At most 12 agent turns and five minutes of generation.
- Model fixed to GPT-4.1 mini via a localhost credential proxy. At most 12 requests,
  64 KB/request, 2,048 output tokens/request, and USD 1 conservative reserved
  token budget per attempt. Reservations include failed requests and are never
  refunded. This is separate from the existing nightly experiment budget.
- Token estimates use $1/M input and $4/M output (above documented $0.40/$1.60
  text pricing: https://developers.openai.com/api/docs/models/gpt-4.1-mini).
  GitHub macOS runner charges are separate; check repository Actions billing.
- Automatic changes limited to pure `clean_japanese_text` / `clean_translation_text`
  bodies and plain `static/style.css`. Max four files and 160 changed tracked lines.
  One new `tests/test_auto_*.py` is mandatory. Existing tests cannot change.
- Authentication, permissions, DB, billing, prompts, dependencies, configuration,
  workflows and all other files require manual approval. No automatic DB migration.
- Baseline must pass, isolated candidate must pass, and the original tests run in
  a separate process so newly generated tests cannot replace their checks.
- Publish only from the unchanged baseline using the existing remote lease check.
- Verify exact deployed revision, home page and anonymous API denial. If this
  fails, revert only when our commit is still the current local AND remote tip,
  then verify the revert deployment. Concurrent changes stop automatic recovery.
- No issue found means no change. A rejected/incomplete repair leaves a failed
  Actions run with a proposal report for inspection, not an unverified patch.

This checks deployment availability and anonymous access, not a full authenticated
post-deploy conversation or visual/mobile correctness. The separate live QA remains
necessary. Reports are Actions artifacts for 14 days; no real learner records are
provided to the repair agent. No Telegram delivery is configured for this job.
