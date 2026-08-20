# ReelRouter

An AI video-generation orchestration and cost-optimization prototype.

## Current capabilities

- Text-to-Video and Image-to-Video request schemas
- Capability/cost/quality-based model routing
- Budget guard and human approval
- Mock provider and Runway provider adapter
- Async job polling and output review
- MySQL persistence for video jobs and output reviews
- FastAPI endpoints and automated tests

## Current limitation

The current version orchestrates individual video-generation jobs.
Keyword-to-story, storyboard planning, multi-shot execution, and video assembly
will be added in subsequent iterations.

## Local development

1. Configure `.env` from `.env.example`.
2. Start MySQL:

   ```powershell
   docker compose up -d