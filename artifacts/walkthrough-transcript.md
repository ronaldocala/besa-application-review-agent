# Three-minute walkthrough transcript

Synthetic narration; prepared with AI assistance. This describes the saved real GPT run included in `sample-run.json`.

## 00:00 — Verified run

This is an AI-narrated walkthrough of the application review agent. The voice is synthetic, and the implementation was prepared with AI assistance. The aim is simple: use a language model to interpret applications, while keeping important decisions under explicit software controls. This screen shows a saved, verified GPT run, not a simulated response. Maria scored one hundred and advanced. John scored zero, with rejection waiting for human approval. Alex scored forty and was routed for more information.

## 00:29 — An explicit scoring policy

The rubric is deliberately small and visible. Support experience contributes up to forty points, daily ticket volume fifteen, a named support tool fifteen, fluent English twenty, and full-time availability ten. Since the brief supplied no full job description, this demo assumes an experienced role requiring one year of support, English fluency, and full-time availability. Those are design assumptions that a hiring manager should approve. Missing information earns no evidence points, but it is not treated as an explicit failure.

## 00:58 — Keep instructions separate from data

The model receives the application as an untrusted record, separate from the trusted policy. Each candidate gets a fresh session. The model extracts facts with exact supporting quotations and calls one of three local functions through MCP. It cannot supply its own score, an approval flag, a different candidate identifier, or a file path. Python validates the schema and evidence, calculates the score, and checks whether the selected tool matches the policy. Shell commands, web search, and unrelated integrations are disabled.

## 01:28 — A rejection is only a proposal

The most important safeguard is in the rejection function itself. It always returns waiting for human approval. There is no model-accessible approval function, and no email is sent. In this demo, John explicitly says he has no experience, which fails the assumed experience requirement. His rejection is therefore only a proposal for a person to review. The audit records the tool arguments, computed decision, and result. A logging failure stops the operation, and a second decision in the same session is blocked.

## 01:57 — Sample C: the attempted override

Alex is the adversarial example. The application includes a fake system note demanding a score of one hundred and advancement. GPT treated that passage as data and flagged it. The code also has a conservative detector for common instruction patterns, as a second layer. Alex retains forty points for two years of support, but gains nothing from the injected command. Missing English and availability evidence, together with the suspicious passage, lead to a request for information and human review, not automatic rejection.

## 02:26 — Tests, limitations, and next steps

The real run log preserves all three completed model tool calls, their results, and hashes of the source files used. Fifteen offline safety tests cover routing, pending rejection, invented evidence, invalid arguments, duplicate calls, and log failure. This is a bounded demonstration, not a claim that prompt injection is solved. Next, agree the rubric with a hiring manager, add an authenticated human review queue and durable retry protection, and evaluate more languages and adversarial phrasing. Production also needs access controls, privacy retention rules, and tamper-evident audit storage.
