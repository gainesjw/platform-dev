"""Collect artifact reviews; deployment selection is a pipeline responsibility."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .inventory import read_json, require, write_json
from .release import verify


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_payload(release, environment):
    release = Path(release)
    return json.dumps(dict(
        workspaceId=read_json(release / "config.json")["environments"][environment]["workspaceId"],
        manifest=read_json(release / "inventory/manifest.json"),
        dependencies=read_json(release / "inventory/dependencies.json")), separators=(",", ":")).encode()


def validate_review(result, payload, environment, policy_digest=None):
    request = json.loads(payload)
    require(isinstance(result, dict), "Invalid policy review")
    require(str(result.get("workspaceId", "")).lower() == request["workspaceId"].lower(), "Policy workspace mismatch")
    require(result.get("environment") == environment, "Policy environment mismatch")
    require(result.get("requestDigest") == hashlib.sha256(payload).hexdigest(), "Policy request digest mismatch")
    require(result.get("manifest") == request["manifest"], "Policy manifest mismatch")
    require(isinstance(result.get("policyVersion"), str) and result["policyVersion"], "Missing policy version")
    require(isinstance(result.get("policyDigest"), str) and len(result["policyDigest"]) == 64,
            "Missing policy digest")
    require(policy_digest is None or result["policyDigest"] == policy_digest, "Policy digest mismatch")
    require(isinstance(result.get("decisionId"), str) and result["decisionId"], "Missing review identity")
    require(isinstance(result.get("findings"), list), "Missing review findings")
    items = result.get("items")
    require(isinstance(items, list) and all(isinstance(i, dict) and isinstance(i.get("logicalId"), str)
            for i in items), "Invalid item reviews")
    require(sorted(i["logicalId"] for i in items) == sorted(i["logicalId"] for i in request["manifest"]["items"]),
            "Policy item set mismatch")
    for item in items:
        require(type(item.get("approved")) is bool and isinstance(item.get("findings"), list), "Invalid item result")
        require(not item["approved"] or not (item["findings"] or result["findings"]), "Passing review has failure findings")
    return {i["logicalId"]: i for i in items}


def review(release, environment, url, receipt, expected, policy_digest=None):
    verify(release, expected)
    target = urlparse(url)
    require(target.scheme == "https" or target.scheme == "http" and target.hostname in {"127.0.0.1", "localhost", "::1"},
            "Use HTTPS, or HTTP on loopback for local development")
    payload = request_payload(release, environment)
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("POLICY_API_KEY"):
        headers["X-Policy-Key"] = key
    request = Request(url.rstrip("/") + "/v1/evaluations", data=payload, headers=headers, method="POST")
    with build_opener(NoRedirects).open(request, timeout=15) as response:
        require(response.status == 200, "Policy API did not return HTTP 200")
        result = json.load(response)
    write_json(receipt, result)
    validate_review(result, payload, environment, policy_digest)
    return result


def select_items(manifest, graph, reviews, mode):
    require(mode in {"passing", "all"}, "Unknown pipeline policy mode")
    selected = {key for key, review in reviews.items() if review["approved"]}
    # Recheck dependency closure at the deployment boundary, even for an inconsistent review.
    for edge in graph["edges"]:
        require(edge["item"] not in selected or edge["dependency"].startswith("external:")
                or edge["dependency"] in selected, "Passing item has an excluded prerequisite")
    require(mode != "all" or len(selected) == len(manifest["items"]), "Pipeline requires all items to pass policy")
    return selected
