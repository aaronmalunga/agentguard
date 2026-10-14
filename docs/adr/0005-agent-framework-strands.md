# ADR-0005: Strands Agents for the demo agent; the guard stays framework-free

- **Status:** Accepted · **Date:** 14 Oct 2026

## Context
AgentGuard has two parts: the **guard** (trusted; decides and moves money) and the **demo shopping agent** (untrusted
client the guard protects). Only the agent needs an agent framework. Options considered: LangGraph (MIT; graph state
machine, human-in-the-loop interrupts, durable execution; official PayPal toolkit integration via LangChain),
Strands Agents (Apache-2.0; lightweight; MCP built in; model-agnostic incl. Amazon Bedrock), or a plain tool-calling loop.

## Decision
- **Strands Agents** for the demo shopping agent and agent-side helpers.
- **The guard uses no agent framework** — plain, deterministic, testable service code.

## Why
- **Trust boundary:** the agent may *ask*; only the guard may *move money*. Keeping probabilistic components out of the
  guard keeps money-moving logic deterministic and testable.
- AgentGuard is designed as a proxy in front of PayPal's MCP tools; Strands speaks MCP natively.
- Same licence (Apache-2.0); runs on Amazon Bedrock or a direct model API (useful before the AWS account is active);
  fits the AWS deployment (ADR-0002).
- LangGraph's main strengths (human-in-the-loop, durable execution) would duplicate what the guard already does.

## Consequences
- ➕ Agent-agnostic by design: any MCP-speaking agent can be protected; the evaluation can add a second client later.
- ➖ Smaller community than LangGraph; we connect to PayPal via its MCP server rather than a framework-specific toolkit.
- Follow-up: choose the LLM provider for development (direct API vs Bedrock). Amazon Bedrock AgentCore (agent hosting,
  framework-agnostic) is roadmap only — considered with the AWS target, not in v1 scope.
