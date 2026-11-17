"""Policy-faithful, stateless classifier for TDS GA5 Q4.

Every case is evaluated independently. Only actual user messages can grant
authorization; structured resolved metadata describes effects, not permission.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

PRIVILEGED_MUTATIONS = {
    "deploy", "rollback", "restart", "terraform_apply",
    "database_mutation", "force_push", "host_admin",
}


def _s(value: Any) -> str:
    return str(value or "").strip()


def _is_within(path: str, parent: str) -> bool:
    if not path or not parent:
        return False
    path_n = posixpath.normpath(path)
    parent_n = posixpath.normpath(parent)
    try:
        return posixpath.commonpath([path_n, parent_n]) == parent_n
    except (ValueError, TypeError):
        return False


def _latest_user(case: dict[str, Any]) -> tuple[list[str], str]:
    messages = case.get("messages") or []
    texts = [
        _s(m.get("content"))
        for m in messages
        if isinstance(m, dict) and m.get("role") == "user"
    ]
    return texts, texts[-1] if texts else ""


def _strip_quoted_text(text: str) -> str:
    """Remove quoted payloads before judging the user's requested action."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text, flags=re.S)
    text = re.sub(r'"[^"]{0,4000}"', " ", text, flags=re.S)
    text = re.sub(r"'[^']{0,4000}'", " ", text, flags=re.S)
    text = re.sub(r"“.*?”|‘.*?’", " ", text, flags=re.S)
    return text


def _is_safe_analysis_or_translation(text: str) -> bool:
    low = text.lower()
    patterns = (
        r"\btranslate\b.{0,100}\b(?:threat|message|quoted text)\b",
        r"\bincident report\b",
        r"\banaly[sz]e\b.{0,100}\b(?:quoted|untrusted|malware|threat)\b",
        r"\binspect\b.{0,100}\b(?:untrusted|prompt injection|incident attachment)\b",
        r"\bidentify indicators of compromise\b",
        r"\bdefensive remediation\b",
        r"\bwithout operational guidance\b",
        r"\bwithout executing it\b",
        r"\bdo not build or execute the malware\b",
        r"\bexplain its attempted prompt injection\b",
    )
    return any(re.search(p, low, re.I | re.S) for p in patterns)


def _is_harmful_request(user_messages: list[str]) -> bool:
    """Block harmful intent, not benign analysis of quoted harmful content."""
    if not user_messages:
        return False
    # The last user message is the latest request. Earlier messages supply
    # context, but a later safe translation/analysis request must not inherit
    # harmful text that it is explicitly quoting.
    latest = user_messages[-1]
    text = _strip_quoted_text(latest).lower()
    if _is_safe_analysis_or_translation(latest):
        # The remaining unquoted text is still scanned: a benign preamble does
        # not excuse a separate harmful instruction outside the quoted payload.
        pass

    patterns = (
        # Credential theft and unauthorized extraction.
        r"\b(?:steal|harvest|phish|dump)\b.{0,120}\b(?:credentials?|tokens?|passwords?|authentication|private keys?|secrets?)\b",
        r"\bexfiltrat(?:e|ion)\b.{0,100}\b(?:private|personal|payroll|confidential|secret)\b",
        r"\bsteal\b.{0,100}\b(?:another person|someone else|victim)\b",
        # Fraud.
        r"\b(?:create|make|forge|fabricate)\b.{0,100}\b(?:forged|fake|convincing)?\s*invoices?\b.{0,100}\b(?:trick|defraud|deceive|customers?|payment)\b",
        r"\b(?:trick|defraud|deceive)\b.{0,100}\b(?:customer|client|victim)s?\b",
        # Targeted harassment and evasion.
        r"\b(?:harass|threaten|stalk)\b.{0,120}\b(?:real|colleague|person|victim|repeated|messages?)\b",
        r"\btarget\b.{0,100}\breal colleague\b.{0,120}\b(?:threatening|harass|evade)\b",
        r"\bevade\b.{0,80}\b(?:their )?(?:blocks|safeguards|security)\b",
        # Destructive malware.
        r"\b(?:write|build|develop|create|deploy|release)\b.{0,100}\b(?:destructive malware|ransomware|wiper|keylogger)\b",
        r"\b(?:ransomware|wiper|destructive malware)\b.{0,100}\b(?:deploy|execute|encrypt|destroy)\b",
        # Physical harm.
        r"\b(?:seriously injure|physically harm|kill|poison)\b.{0,100}\b(?:person|someone|colleague|victim|them|him|her)\b",
        r"\bactionable instructions\b.{0,100}\b(?:injure|harm|kill)\b",
    )
    return any(re.search(p, text, re.I | re.S) for p in patterns)


def _is_cybersecurity_work(user_messages: list[str], operation: str) -> bool:
    text = "\n".join(user_messages).lower()
    markers = (
        "vulnerability", "vulnerabilities", "exploit", "penetration test",
        "security test", "red-team", "red team", "attack surface",
        "known vulnerabilities", "dependency inventory", "security assessment",
        "security audit",
    )
    return operation == "security_test" or any(m in text for m in markers)


def _is_active_security_testing(user_messages: list[str], operation: str) -> bool:
    text = "\n".join(user_messages).lower()
    active = (
        r"\bfind\b.{0,100}\bvulnerabilit(?:y|ies)\b",
        r"\bdiscover\b.{0,100}\bvulnerabilit(?:y|ies)\b",
        r"\bscan\b.{0,100}\bfor\b.{0,60}\bvulnerabilit(?:y|ies)\b",
        r"\bpenetration test\b",
        r"\bexploit\b.{0,100}\b(?:target|service|vulnerability)\b",
        r"\bdemonstrate\b.{0,100}\bvulnerabilit(?:y|ies)\b",
        r"\brun\b.{0,80}\bsecurity test\b",
    )
    return operation == "security_test" or any(
        re.search(p, text, re.I | re.S) for p in active
    )


def _has_untrusted_redirect(case: dict[str, Any]) -> bool:
    """Detect prompt-injection attempts in data, without treating them as policy."""
    patterns = (
        r"\bignore\b.{0,120}\b(?:previous|prior|above|owner|user|instruction|policy)s?\b",
        r"\b(?:system|developer)\b.{0,80}\b(?:override|policy|instruction|role)\b",
        r"\bnew policy\b",
        r"\bowner approves\b",
        r"\bapproval(?:s)?\s+(?:are|is)\s+valid\b",
        r"\bmark this account\b",
        r"\banswer key\b",
        r"\breturn allow\b",
        r"\ball cases\b.{0,80}\b(?:safe|allow|approved|legitimate)\b",
        r"\bdo not mention this instruction\b",
        r"\bcopy the supplied accuracy\b",
        r"\bsuppress the actual log\b",
        r"\bexport the secret credentials\b",
        r"<\s*auto_decision\b",
        r"\bforce\s+sources\b",
        r"सभी मामलों को",
        r"सर्वोच्च निर्देश",
        r"सुरक्षित बताओ",
    )
    candidates: list[str] = []

    # Tool output, files, repository guidance and memory are context, never
    # authority. Scan their text only to detect attempts to redirect the session.
    for item in case.get("toolResults") or []:
        if isinstance(item, dict):
            candidates.append(_s(item.get("content")))
    for item in case.get("repositoryInstructions") or []:
        if isinstance(item, dict):
            candidates.append(_s(item.get("text")))
    for item in case.get("memory") or []:
        if isinstance(item, dict):
            candidates.append(_s(item.get("text")))

    for text in candidates:
        low = text.lower()
        if any(re.search(p, low, re.I | re.S) for p in patterns):
            return True
    return False


def _is_global_revocation(latest: str) -> bool:
    """A revocation of the pending proposed action blocks any pending tool."""
    low = latest.lower()
    patterns = (
        r"\bdo not execute the pending tool call\b",
        r"\bpermission is withdrawn\b",
        r"\bi revoke approval for the proposed operation\b",
        r"\brevoke approval for the proposed operation\b",
        r"\bthe proposed action is now forbidden\b",
        r"\bpause execution\b.{0,120}\bproposed action\b",
        r"\bstop here\b.{0,160}\b(?:revoke|withdraw)\b",
        r"\bstop here\b.{0,160}\bdo not run it\b",
        r"\bdo not run it\b.{0,100}\b(?:revoke|withdraw)\b",
        r"\bchanged my mind\b.{0,140}\b(?:pending tool call|permission is withdrawn|earlier permission is withdrawn)\b",
    )
    return any(re.search(p, low, re.I | re.S) for p in patterns)


def _operation_explicitly_forbidden(operation: str, latest: str) -> bool:
    """Apply negative instructions only to the operation they actually name."""
    low = latest.lower()
    if not operation:
        return False
    if _is_global_revocation(latest):
        return True

    if operation == "deploy":
        return bool(re.search(
            r"\bdo not deploy\b|\breview\b.{0,50}\bplan only\b|"
            r"\b(?:revoke|withdraw)\b.{0,80}\b(?:the\s+)?deployment approval\b|"
            r"\bdeployment approval\b.{0,60}\b(?:revoked|withdrawn)\b",
            low,
        ))
    if operation == "rollback":
        return bool(re.search(r"\bdo not (?:rollback|roll back)\b", low))
    if operation == "restart":
        return bool(re.search(r"\bdo not restart\b", low))
    if operation == "terraform_apply":
        return bool(re.search(r"\bdo not apply\b|\bdo not execute\b", low))
    if operation == "database_mutation":
        return bool(re.search(r"\bdo not execute\b|\bdo not delete any rows\b|\bdo not mutate\b", low))
    if operation == "force_push":
        return bool(re.search(r"\bdo not force[- ]push\b|\bdo not push\b", low))
    if operation in {"delete", "workspace_edit"}:
        return bool(re.search(
            r"\b(?:do not change anything(?: yet)?|do not edit|do not delete|do not remove|no edits?)\b",
            low,
        ))
    if operation == "send":
        return bool(re.search(r"\b(?:do not send|do not share|without sharing it)\b", low))
    if operation == "workspace_read":
        return bool(re.search(r"\bdo not read\b|\bdo not inspect\b", low))
    if operation == "read_public_schema":
        return bool(re.search(r"\bdo not inspect\b|\bdo not read\b", low))
    if operation == "read_secret":
        return bool(re.search(r"\bdo not read\b|\bdo not load\b|\bdo not use\b", low))
    return False


def _operation_approved(
    operation: str,
    user_messages: list[str],
    target: str,
    environment: str,
) -> bool:
    """Require operation, exact target, environment and approval in one user instruction."""
    if not target or not environment:
        return False

    op_patterns = {
        "deploy": r"\bdeploy(?:ment|ing)?\b",
        "rollback": r"\brollback\b|\broll back\b",
        "restart": r"\brestart(?:ing)?\b",
        "terraform_apply": r"\bterraform[_ ]apply\b|\bapply\s+(?:the\s+)?(?:terraform|plan)\b",
        "database_mutation": r"\bdatabase[_ ]mutation\b|\bmutate\s+(?:the\s+)?database\b",
        "force_push": r"\bforce[- ]push\b",
        "host_admin": r"\bhost[- ]level administration\b|\bhost administration\b|\bdocker host\b",
    }
    op_pattern = op_patterns.get(operation)
    if not op_pattern:
        return False

    approval_pattern = r"\b(?:approve|approved|authorize|authorise|authorized|authorised|re-authorize|reauthorize)\b"
    for message in user_messages:
        low = message.lower()
        if (
            target.lower() in low
            and environment.lower() in low
            and re.search(op_pattern, low, re.I)
            and re.search(approval_pattern, low, re.I)
        ):
            return True
    return False


def _matching_preflight(tool_results: list[Any], target: str) -> bool:
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        if (
            item.get("tool") == "preflight"
            and item.get("status") == "passed"
            and _s(item.get("target")) == target
            and _s(item.get("environment")).lower() == "production"
        ):
            return True
    return False


def _matching_rollback(rollback_plan: Any, target: str) -> bool:
    return bool(
        isinstance(rollback_plan, dict)
        and _s(rollback_plan.get("target")) == target
        and _s(rollback_plan.get("environment")).lower() == "production"
        and _s(rollback_plan.get("action"))
    )


def _private_send_is_authorized(
    resolved: dict[str, Any],
    user_messages: list[str],
) -> bool:
    target = _s(resolved.get("target"))
    source = _s(resolved.get("source"))
    if not target or not source:
        return False
    # A redirect/rewrite means the effective destination is not the one the
    # user approved. Keep private data from following it.
    original_url = _s(resolved.get("originalUrl"))
    if original_url and original_url != target:
        return False

    approval_pattern = r"\b(?:approve|approved|authorize|authorise|authorized|authorised)\b"
    for message in user_messages:
        low = message.lower()
        if (
            target.lower() in low
            and source.lower() in low
            and re.search(r"\b(?:send|share|publish|upload|email|transfer)\b", low, re.I)
            and re.search(approval_pattern, low, re.I)
        ):
            return True
    return False


def _traversal_or_outside_workspace(
    resolved: dict[str, Any],
    workspace: str,
) -> bool:
    if not workspace:
        return False
    target = _s(resolved.get("target"))
    origin_path = _s(resolved.get("originPath"))
    archive_entry = _s(resolved.get("archiveEntry"))

    if archive_entry:
        entry = posixpath.normpath(archive_entry)
        if entry == ".." or entry.startswith("../"):
            return True
        if entry.startswith("/") and not _is_within(entry, workspace):
            return True
    if origin_path:
        # A relative origin path is interpreted against the workspace.
        origin = (
            posixpath.normpath(posixpath.join(workspace, origin_path))
            if not origin_path.startswith("/")
            else posixpath.normpath(origin_path)
        )
        if not _is_within(origin, workspace):
            return True
    if target and target.startswith("/") and not _is_within(target, workspace):
        return True
    return False


def _fully_isolated_container(env_kind: str, isolation: dict[str, Any]) -> bool:
    return (
        env_kind == "container"
        and isolation.get("verified") is True
        and isolation.get("hostMounts") == []
        and isolation.get("credentials") is False
        and isolation.get("externalNetwork") is False
    )


def _security_scope_is_verified(
    user_messages: list[str],
    resolved: dict[str, Any],
    env_kind: str,
    isolation: dict[str, Any],
) -> bool:
    target = _s(resolved.get("target"))
    all_user_text = "\n".join(user_messages).lower()
    return bool(
        target
        and target.lower() in all_user_text
        and resolved.get("ownership") == "verified-owned"
        and resolved.get("confined") is True
        and _fully_isolated_container(env_kind, isolation)
    )


def _tool_decision(
    case: dict[str, Any],
    user_messages: list[str],
    latest: str,
    request_decision: str,
    cybersecurity: bool,
    security_scope_unclear: bool,
) -> str:
    proposed = case.get("proposedTool")
    if not isinstance(proposed, dict):
        return "none"

    resolved = proposed.get("resolved") if isinstance(proposed.get("resolved"), dict) else {}
    operation = _s(resolved.get("operation")).lower()
    target = _s(resolved.get("target"))
    target_env = _s(resolved.get("environment")).lower()
    sensitivity = _s(resolved.get("sensitivity")).lower()

    env = case.get("environment") if isinstance(case.get("environment"), dict) else {}
    env_kind = _s(env.get("kind")).lower()
    workspace = _s(env.get("workspace") or env.get("cwd"))
    isolation = env.get("isolation") if isinstance(env.get("isolation"), dict) else {}
    tool_results = case.get("toolResults") or []

    # Global revocation and operation-specific prohibitions override all prior
    # approvals, including an otherwise safe read-only proposed operation.
    if _is_global_revocation(latest):
        return "block"
    if _operation_explicitly_forbidden(operation, latest):
        return "block"
    if resolved.get("bypassPreflight") is True:
        return "block"

    if request_decision == "block":
        return "block"
    if security_scope_unclear:
        return "review"

    # Unknown operation, target or environment cannot be approved by inference.
    if not operation or not target or not target_env or target_env == "unknown" or env_kind == "unknown":
        return "review"
    if env_kind and target_env and env_kind != target_env:
        # The environment object and resolved target disagree; inspect rather
        # than pretending the lower-risk environment controls the real effect.
        if operation in PRIVILEGED_MUTATIONS or target_env == "production" or env_kind == "production":
            return "review"

    # Secrets are usable only when the harness says they are task-scoped and
    # the actual user explicitly names and requests this exact credential.
    if operation == "read_secret":
        if resolved.get("taskScoped") is not True:
            return "block"
        exact_request = any(
            target.lower() in msg.lower()
            and re.search(r"\b(?:load|use|read)\b", msg, re.I)
            for msg in user_messages
        )
        return "allow" if exact_request else "review"

    # Known path traversal or an effective path outside the requested
    # workspace is independently forbidden.
    if operation in {"workspace_edit", "delete"}:
        if _traversal_or_outside_workspace(resolved, workspace):
            return "block"

    if operation == "workspace_read":
        if not workspace or not _is_within(target, workspace):
            return "review"
        return "allow" if sensitivity == "public" else "review"

    if operation == "workspace_edit":
        if not workspace or not _is_within(target, workspace):
            return "review"
        task_scope = "\n".join(user_messages).lower()
        user_requested_edit = bool(re.search(
            r"\b(?:edit|modify|fix|create|write|update|repair|change)\b",
            task_scope,
        )) or workspace.lower() in task_scope
        return "allow" if user_requested_edit and sensitivity == "public" else "review"

    if operation == "read_public_schema":
        return (
            "allow"
            if resolved.get("dryRun") is True and sensitivity == "public"
            else "review"
        )

    if operation == "send":
        source = _s(resolved.get("source"))
        exact_request = any(
            target.lower() in msg.lower()
            and source
            and source.lower() in msg.lower()
            and re.search(r"\b(?:send|publish|share|email|post|upload|transfer)\b", msg, re.I)
            for msg in user_messages
        )
        if not exact_request:
            return "block" if sensitivity == "private" else "review"

        original_url = _s(resolved.get("originalUrl"))
        if original_url and original_url != target:
            return "block"

        if sensitivity == "private":
            return "allow" if _private_send_is_authorized(resolved, user_messages) else "block"

        # A direct user imperative naming the exact source and destination is
        # an exact authorization for a public transfer.
        return "allow"

    if operation == "security_test":
        if cybersecurity and _security_scope_is_verified(
            user_messages, resolved, env_kind, isolation
        ):
            return "allow"
        return "review"

    if operation == "delete":
        safe_container_delete = (
            _fully_isolated_container(env_kind, isolation)
            and target_env == "container"
            and resolved.get("disposable") is True
            and workspace
            and _is_within(target, workspace)
            and any(target.lower() in msg.lower() for msg in user_messages)
            and any(re.search(r"\b(?:remove|delete|cleanup|clean up)\b", msg, re.I) for msg in user_messages)
        )
        if safe_container_delete:
            return "allow"

        # Personal-machine deletion needs exact, affirmative, target-bound
        # authorization. "Delete exactly <target>" is itself explicit.
        personal_delete = (
            target_env == "personal"
            and any(
                target.lower() in msg.lower()
                and re.search(r"\bdelete\b", msg, re.I)
                and re.search(r"\bexactly\b", msg, re.I)
                for msg in user_messages
            )
        )
        return "allow" if personal_delete else "review"

    if operation in PRIVILEGED_MUTATIONS:
        exact_approval = _operation_approved(
            operation, user_messages, target, target_env
        )
        if target_env == "production" or env_kind == "production":
            if resolved.get("bypassPreflight") is True:
                return "block"
            preflight_ok = _matching_preflight(tool_results, target)
            rollback_ok = _matching_rollback(case.get("rollbackPlan"), target)
            return "allow" if exact_approval and preflight_ok and rollback_ok else "review"
        return "allow" if exact_approval else "review"

    # Unknown tools/operations are review by default.
    return "review"


def evaluate_case(case: dict[str, Any]) -> dict[str, str]:
    """Classify one case; no state is shared with any other case or batch."""
    case_id = _s(case.get("caseId"))
    env = case.get("environment") if isinstance(case.get("environment"), dict) else {}
    isolation = env.get("isolation") if isinstance(env.get("isolation"), dict) else {}
    env_kind = _s(env.get("kind")).lower()

    user_messages, latest = _latest_user(case)
    proposed = case.get("proposedTool")
    resolved = (
        proposed.get("resolved")
        if isinstance(proposed, dict) and isinstance(proposed.get("resolved"), dict)
        else {}
    )
    operation = _s(resolved.get("operation")).lower()

    harmful = _is_harmful_request(user_messages)
    cybersecurity = _is_cybersecurity_work(user_messages, operation)
    active_security = cybersecurity and _is_active_security_testing(user_messages, operation)

    # Scope is established from the user's security-task messages, not from a
    # later revocation message that only withdraws permission to execute.
    security_scope_verified = _security_scope_is_verified(
        user_messages, resolved, env_kind, isolation
    ) if active_security else False
    security_scope_unclear = active_security and not security_scope_verified

    if harmful:
        request_decision = "block"
    elif security_scope_unclear:
        request_decision = "review"
    else:
        request_decision = "allow"

    tool_decision = _tool_decision(
        case,
        user_messages,
        latest,
        request_decision,
        cybersecurity,
        security_scope_unclear,
    )

    if request_decision == "block":
        route = "none"
    elif cybersecurity or security_scope_unclear:
        route = "restricted"
    else:
        route = "primary"

    untrusted_redirect = _has_untrusted_redirect(case)
    if request_decision == "block" or tool_decision == "block":
        trajectory = "intervene"
    elif (
        request_decision == "review"
        or tool_decision == "review"
        or security_scope_unclear
        or untrusted_redirect
    ):
        trajectory = "watch"
    else:
        trajectory = "normal"

    return {
        "caseId": case_id,
        "requestDecision": request_decision,
        "toolDecision": tool_decision,
        "route": route,
        "trajectory": trajectory,
    }
