# A2A integration

BankScope exposes an **A2A 0.3 JSON-RPC service**, implemented with the public A2A Python SDK. Another agent or compatible client can discover its skills, submit questions and track tasks. The executor calls the same TreasuryAgent and real MCP subprocess as the web UI. It uses the local synthetic database in both local-planner and optional model modes.

~~~mermaid
sequenceDiagram
    participant Caller as External A2A client
    participant API as BankScope A2A service
    participant Agent as TreasuryAgent
    participant MCP as Local MCP tools
    participant DB as Synthetic SQLite
    Caller->>API: GET /.well-known/agent-card.json
    API-->>Caller: Skills, JSON-RPC URL, streaming capability
    Caller->>API: message/stream (text, optional contextId)
    API-->>Caller: submitted → working
    API->>Agent: stream(question, conversation state)
    Agent->>MCP: call_tool(name, validated arguments)
    MCP->>DB: Read-only SQL
    DB-->>MCP: Records
    MCP-->>Agent: Calculated report
    Agent-->>API: Tool results and answer
    API-->>Caller: JSON artifact + text artifact → completed
    Caller->>API: tasks/get (taskId)
    API-->>Caller: Stored task status and artifacts
~~~

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| GET /.well-known/agent-card.json | Discover the seven skills and advertised JSON-RPC endpoint |
| POST /a2a | Standard A2A JSON-RPC requests |
| GET / | Existing web workspace |
| /api/chat, /api/report, /api/export.csv | Existing web APIs; separate from the A2A protocol |

| JSON-RPC method | Behavior |
| --- | --- |
| message/send | Return a completed Task by default; configuration.blocking=false returns an active task for polling |
| message/stream | SSE stream of the initial Task, status updates and artifact updates |
| tasks/get | Retrieve task status and artifacts by ID |
| tasks/cancel | Cancel active execution; terminal tasks return TaskNotCancelable |

The SDK also provides the protocol's running-task resubscription handler. This is not persistent event replay. Push notifications, authenticated extended cards, gRPC and HTTP+JSON transport are not advertised.

## Start and connect

~~~bash
./run.sh
~~~

In another terminal, use the included **official SDK client**:

~~~bash
.venv/bin/python examples/a2a_client.py
.venv/bin/python examples/a2a_client.py --stream
~~~

Both examples discover the Agent Card, request a Harbor report, reuse its context for a fee follow-up and retrieve the stored task. To choose questions:

~~~bash
.venv/bin/python examples/a2a_client.py --stream \
  --message 'Show the overall relationship report for 2026Q3' \
  --message 'Compare fees for all banks'
~~~

The Agent Card's URL comes from **BANK_AGENT_PUBLIC_URL**, defaulting to http://127.0.0.1:8000. When running on a different port, set the advertised URL as well:

~~~bash
export BANK_AGENT_PUBLIC_URL=http://127.0.0.1:8767
.venv/bin/python -m uvicorn bank_agent.web:app --host 127.0.0.1 --port 8767
.venv/bin/python examples/a2a_client.py --base-url http://127.0.0.1:8767 --stream
~~~

Run the client command in a separate terminal while the server is running. For a compatible A2A 0.3 JSON-RPC client, provide the discovery URL or the advertised /a2a endpoint according to that client's configuration. This repository includes an SDK interoperability example; it does not automatically register itself inside an AgentHub instance.

## Raw JSON-RPC example

~~~bash
curl http://127.0.0.1:8000/a2a \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"example-1","method":"message/send","params":{"message":{"role":"user","messageId":"example-message-1","parts":[{"kind":"text","text":"Show Harbor credit utilization for 2026Q3"}]}}}'
~~~

The result is a Task with an ID, contextId, terminal status and artifacts. Each successful tool result becomes a named JSON DataPart containing tool and result fields, including the synthetic-data marker. The final answer is a TextPart in answer.txt. Clients should consume both rather than treating the final status message as the full report.

For follow-ups, use a **new messageId**, retain the returned **contextId** and omit taskId. This starts a new task in the same conversation. Completed tasks cannot be reopened. The web chat session ID and A2A context ID are separate namespaces.

## Lifecycle and scope

- Normal execution: submitted → working → completed, with intermediate working updates carrying planner/tool information.
- Unsupported query parameters or execution failures: failed, with a generic diagnostic and no provider credentials in the status.
- Invalid protocol/input: JSON-RPC error. Inputs must be user text messages of 1–2000 characters. File and DataPart inputs are not accepted.
- Active cancellation: canceled. The producer stops; a failed or canceled turn does not overwrite the last successful conversation state.
- Same-context turns execute serially. Up to 128 conversation states are retained, evicting idle contexts when needed. Tasks and state live in process memory, reset on restart and are not shared across workers.

This remains a **single-user local service without authentication**. A2A adds interoperable agent communication; it does not restore company identity, tenant isolation, deployment, billing, long-term memory or enterprise integrations. Bind it to loopback for local use; a multi-user deployment requires a separate authenticated service boundary and persistent state.

The README GIF demonstrates the web/MCP path. A2A is demonstrated by the SDK example and protocol tests, not by that recording. The default mode remains a deterministic planner; configuring a model does not change the A2A or MCP interfaces.
