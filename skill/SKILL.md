---
name: wizard-connectors
description: Use for content-free connector readiness and summary job status.
---
# Connected accounts
Use connector_status for readiness; summary_job_status accepts an owner-issued opaque job ID. These MCP tools never return conversations, titles, senders or summaries. Open the human view for fictional chat selection and results. Never request owner tokens or Google passwords in chat. Google setup is self-serve in Your Google app. The owner creates a Google Cloud Web OAuth client, pastes its ID and secret into that owner-only form, then connects each account and explicitly grants Calendar read-only consent and binding. Never ask for the client secret in chat. Calendar app API uses X-Wizard-Grant at http://wizard-connectors-calendar:8799/service/calendar/ (see docs/CALENDAR_API.md); MCP deliberately exposes no calendar lists or events. Real chat is not connected. No provider replacement or fallback is permitted.
