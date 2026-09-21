"""Educational ticket router. Default mode uses a clearly labelled fixture."""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
QUESTION_VERSION = "support-routing-1"
DEPARTMENTS = {"billing", "technical", "other"}
REVIEW_LOW = 0.25
HUMAN_HIGH = 0.80
CHOICE_MIN = 0.75
CONFIDENCE_MIN = 0.50

QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": (
            "Which team should handle the primary issue "
            "in the latest customer message?"
        ),
        "criteria": {
            "billing": "Charges, invoices, payment failures, refund requests.",
            "technical": "Login failures, application errors, broken features.",
            "other": "Requests outside billing and technical support.",
        },
    },
    "requests_human_agent": {
        "type": "noul",
        "instructions": (
            "Does the latest customer message explicitly request "
            "speaking with a human support agent?"
        ),
        "criteria": {
            "true": "An explicit request for a human agent or specialist.",
            "false": "No explicit request; asking if this is a bot is not enough.",
        },
    },
    "impact": {
        "type": "score",
        "instructions": (
            "What functional impact does the customer report? "
            "Use only stated evidence, not assumptions about other users."
        ),
        "criteria": [
            "No functional failure is reported.",
            "A feature is impaired but a usable workaround is stated.",
            "The customer's main task is blocked with no stated workaround.",
        ],
    },
}

FIXTURE = {
    "model": "educational-fixture",
    "answers": {
        "department": {
            "type": "choice",
            "choice": "technical",
            "probabilities": {"billing": 0.05, "technical": 0.90, "other": 0.05},
            # Illustrative metadata, not a claimed Jev calculation.
            "confidence": 0.72,
        },
        "requests_human_agent": {"type": "noul", "noul": 0.92},
        "impact": {
            "type": "score",
            "score": 1.8,
            "probabilities": {"0": 0.05, "1": 0.10, "2": 0.85},
            "confidence": 0.64,
            "legend": {str(i): v for i, v in enumerate(QUESTIONS["impact"]["criteria"])},
        },
    },
}


def number(value: Any, label: str, high: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a number")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= high:
        raise ValueError(f"{label}: number outside [0, {high}]")
    return result


def distribution(value: Any, keys: set[str], label: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}: unexpected options")
    result = {key: number(v, f"{label}.{key}") for key, v in value.items()}
    if abs(sum(result.values()) - 1.0) > 0.01:
        raise ValueError(f"{label}: probabilities do not sum to one")
    return result


def validate_response(payload: Any) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str):
        raise ValueError("Missing response model")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("Missing answers object")
    for key, expected in (
        ("department", "choice"),
        ("requests_human_agent", "noul"),
        ("impact", "score"),
    ):
        answer = answers.get(key)
        if not isinstance(answer, dict) or answer.get("type") != expected:
            raise ValueError(f"{key}: missing or wrong answer type")

    department = answers["department"]
    if department.get("choice") not in DEPARTMENTS:
        raise ValueError("Unknown department")
    probs = distribution(department.get("probabilities"), DEPARTMENTS, "department")
    if probs[department["choice"]] + 1e-6 < max(probs.values()):
        raise ValueError("Selected department is not a maximum")
    number(department.get("confidence"), "department.confidence")
    number(answers["requests_human_agent"].get("noul"), "human.noul")
    impact = answers["impact"]
    score = number(impact.get("score"), "impact.score", high=2.0)
    levels = distribution(impact.get("probabilities"), {"0", "1", "2"}, "impact")
    expected = sum(int(key) * value for key, value in levels.items())
    if abs(score - expected) > 0.02:
        raise ValueError("Score does not match its distribution")
    number(impact.get("confidence"), "impact.confidence")
    return answers


def build_request(message: str, ticket_id: str) -> dict:
    if not message.strip():
        raise ValueError("Message must not be empty")
    return {
        "model": "jev-latest",
        "state": {
            "ticket_id": ticket_id,
            "messages": [{"role": "customer", "text": message}],
        },
        "questions": copy.deepcopy(QUESTIONS),
    }


def call_typesafe(request_body: dict) -> dict:
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise ValueError("Set TYPESAFE_API_KEY before using --live")
    encoded = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=encoded,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Do not print credentials or the full request.
        raise RuntimeError(f"TypeSafe returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("TypeSafe network request failed or timed out") from None


def decide(payload: dict) -> dict:
    answers = validate_response(payload)
    human_p = answers["requests_human_agent"]["noul"]
    department = answers["department"]
    selected = department["choice"]
    selected_p = department["probabilities"][selected]

    if human_p >= HUMAN_HIGH:
        queue, reason = "human-support", "explicit-human-request"
    elif human_p >= REVIEW_LOW:
        queue, reason = "manual-review", "ambiguous-human-request"
    elif selected_p < CHOICE_MIN or department["confidence"] < CONFIDENCE_MIN:
        queue, reason = "manual-review", "uncertain-department"
    else:
        queue, reason = selected, "clear-department"

    # Severity remains a review signal, not a hidden automatic action.
    return {
        "queue": queue,
        "reason": reason,
        "impact_score": answers["impact"]["score"],
        "response_model": payload["model"],
        "question_version": QUESTION_VERSION,
        "answers": answers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--ticket-id", default="demo-ticket-481")
    parser.add_argument(
        "--message",
        default="I cannot sign in. Please connect me with a support specialist.",
    )
    args = parser.parse_args()
    try:
        request_body = build_request(args.message, args.ticket_id)
        payload = call_typesafe(request_body) if args.live else copy.deepcopy(FIXTURE)
        result = decide(payload)
        result["mode"] = "live" if args.live else "fixture-not-model-inference"
        result["ticket_id"] = args.ticket_id
        if not args.live:
            result["notice"] = "Changing --message does not change the fixed fixture."
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
