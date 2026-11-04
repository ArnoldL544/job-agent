"""Offline, evidence-preserving JD-to-resume selection (chunk-v0.5).

Rank three nested levels (section / entry / bullet).  Match BOTH named
technologies and capability evidence (e.g. event handling -> frontend).
Selection is a recommendation only; original assertions are never rewritten.

chunk-v0.5:
- JD skill regexes no longer fire on ordinary prose ("the rest of", "hybrid
  work model", "networking opportunities", "Grade C").
- JD role weights are graded by how often and WHERE a family is mentioned
  (requirements > responsibilities > other; company/benefits/EEO text ignored),
  instead of 0/1 flags that lit up almost every family.
- select_chunks(..., page_budget=PageModel) fills one page by estimated
  height: relevant technical bullets first, then remaining technical bullets,
  then leadership/awards if space is left. Without page_budget the legacy
  fixed-count behaviour is unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

# Skill detection remains exact: C does not imply C++, Java != JavaScript.
SKILL_REGEX = {
    'python': r'\bpython\b', 'java': r'\bjava\b(?!script)',
    'javascript': r'\bjavascript\b|\bjava\s*script\b',
    'typescript': r'\btypescript\b', 'c++': r'(?<!\w)c\+\+(?!\w)',
    'c': r'(?<![\w+#])c(?![\w+#])', 'c#': r'(?<!\w)c#(?!\w)',
    'sql': r'\bsql\b', 'postgresql': r'\bpostgres(?:ql)?\b',
    'mongodb': r'\bmongodb\b', 'react': r'\breact(?:js|\.js)?\b',
    'next.js': r'\bnext(?:\.js|js)\b', 'node.js': r'\bnode(?:\.js|js)\b',
    'git': r'\bgit\b(?!hub)', 'github': r'\bgithub\b',
    'docker': r'\bdocker\b', 'kubernetes': r'\bkubernetes\b|\bk8s\b',
    'aws': r'\baws\b|\bamazon web services\b',
    # v0.5: bare "rest" ("the rest of the summer") is not an API.
    'api': r'\bapis?\b|\brestful\b|\brest\s+(?:apis?|services?|endpoints?)\b', 'playwright': r'\bplaywright\b',
    'pandas': r'\bpandas\b', 'numpy': r'\bnumpy\b',
    'scikit-learn': r'\bscikit[- ]learn\b|\bsklearn\b',
    'pytorch': r'\bpytorch\b|\btorch\b',
    'machine learning': r'\bmachine learning\b|\bml\b',
    'llm': r'\bllms?\b|\blarge language models?\b',
    'ai agents': r'\bai agents?\b|\bagentic\b|\bagent workflows?\b',
    'data analysis': r'\bdata anal(?:ysis|ytics|yst)\b',
    'data engineering': r'\bdata engineer(?:ing)?\b|\betl\b|\bdata pipeline\b',
    'testing': r'\b(?:unit|integration|automated) tests?\b|\btesting\b|\btest cases?\b',
    'debugging': r'\bdebug(?:ging|ged)?\b',
    # v0.5: "networking opportunities/events" is career prose, not systems work.
    'networking': r'\bnetwork(?:ing)?\s+(?:protocols?|traffic|packets?|programming|stack|security)\b|\btcp/ip\b|\bsocket programming\b',
    'parsing': r'\bpars(?:e|er|ing|ers)\b',
    'algorithms': r'\balgorithms?\b|\bdata structures\b',
    'full stack': r'\bfull[- ]stack\b',
    'backend': r'\bback[- ]end\b', 'frontend': r'\bfront[- ]end\b',
    # v0.5: "hybrid work model" / "business model" are not modeling work.
    'modeling': (r'\bmodell?ing\b|\b(?:statistical|predictive|machine[- ]learning|ml|regression|'
                 r'recommendation|classification|language|data|forecasting)\s+models?\b'),
}
# 'c' is matched case-sensitively: capital C only, never "C-suite"/"Objective-C".
REGEX = {k: re.compile(v, flags=re.IGNORECASE) for k, v in SKILL_REGEX.items() if k != 'c'}
REGEX['c'] = re.compile(r'(?<![\w+#.\-])C(?![\w+#\-])')
REQUIRED_HEADERS = re.compile(
    r'^(?:basic\s+|minimum\s+|required\s+)?(?:required|minimum|must.haves?|qualifications|requirements|'
    r'what you.ll need|what (?:we|they).re looking for|who you are|you have|skills\s*(?:&|and)\s*qualifications)\b', re.I)
PREFERRED_HEADERS = re.compile(r'^(?:preferred|nice.to.haves?|bonus|desired|pluses|additional qualifications)\b', re.I)
RESPONSIBILITY_HEADERS = re.compile(
    r'^(?:responsibilities|key responsibilities|about the role|the role|role overview|what you.ll do|'
    r'your impact|day.to.day|duties|job description|description|overview|position summary)\b', re.I)
# Zero-weight: never describes the work itself.
BOILERPLATE_HEADERS = re.compile(
    r'^(?:benefits|perks|what we offer|what this job offers|the package|compensation|salary|pay range|'
    r'equal (?:employment )?opportunity|eeo|diversity|accommodations?|similar jobs|more jobs|people also|'
    r'alumni in similar roles|about the employer|at a glance)\b', re.I)
# v0.5.1: company intros often describe the actual work ("systems programming",
# "data analysis"), so they count at half weight instead of being skipped.
COMPANY_HEADERS = re.compile(
    r'^(?:about us|about the company|about [A-Z][\w&.\- ]{0,40}$|who we are|our company|our mission|'
    r'a day at\b|life at\b|our culture)', re.I)
OTHER_HEADERS = RESPONSIBILITY_HEADERS  # backward-compatible name
WORK_INTRO = re.compile(r'^(?:during (?:your|the) internship\b|(?:as an intern|in this role),? you will\b|'
                        r'(?:projects? )?you.ll work on\b|you will (?:probably |likely )?work on\b)', re.I)
# Section weights for JD role families (boilerplate never counts).
SECTION_WEIGHT = {'required': 2.0, 'preferred': 1.5, 'responsibilities': 1.5, 'mentioned': 1.0,
                  'company': 0.5, 'boilerplate': 0.0}
WEAK_JD_SIGNAL = 2.0  # below this raw score the JD is treated as "not enough to tailor"

# Capabilities are evidence of role responsibilities, NOT a claim that the
# applicant has a specific technology.  Front-end design is not React mastery.
CAPABILITY_PATTERNS = {
    'frontend_ui': [r'\bfront[- ]end\b', r'\buser (?:interface|interaction)',
                    r'\binterfaces?\b', r'\binteractive\b', r'\b(?:web|mobile) (?:app|application|page)',
                    r'\bpages? navigation\b', r'\bdynamic content\b',
                    r'\bevent handling\b', r'\b(?:wxml|wxss|javascript|react|typescript)\b',
                    r'\b(?:dashboard|(?:ui|front[- ]end) components?)\b', r'\bfull[- ]stack\b'],
    'backend_api': [r'\bback[- ]end\b', r'\bapis?\b', r'\brest\b',
                    r'\bpipelines?\b', r'\bautomated\b', r'\bautomation\b',
                    r'\bserver\b', r'\bdata retrieval\b', r'\bfull[- ]stack\b'],
    'agent_llm': [r'\bai agents?\b', r'\bagentic\b', r'\bllms?\b',
                  r'\bopenai\b', r'\blong[- ]term memory\b',
                  r'\bagent workflows?\b', r'\bscope[- ]aware memory\b',
                  r'\bmemory consolidation\b', r'\bcontext[- ]specific exceptions\b'],
    'data_ml': [r'\bdata anal\w*\b', r'\bdata (?:mining|modeling|engineering)\b',
                r'\bdatasets?\b', r'\bratings?\b', r'\b(?:collaborative filtering|recommender|recommendation)\b',
                r'\b(?:benchmark(?:ed|ing)?|svd|pandas|statistics|regression)\b',
                r'\bmachine learning\b'],
    'systems': [r'\bc\+\+\b', r'\bnetwork\b', r'\bprotocols?\b',
                r'\b(?:parser|parsing|automata|debugging|unit tests?|integration tests?)\b'],
    'user_product': [r'\b(?:appointment|booking|service listing|service browsing)\b',
                     r'\buser interactions?\b', r'\buser[- ]facing\b',
                     r'\binteractive\b', r'\bpage navigation\b'],
}
CAPS = {k: [re.compile(p, re.I) for p in patterns] for k, patterns in CAPABILITY_PATTERNS.items()}

# v0.5: JD-side role evidence is stricter than bullet-side evidence. Words such as
# "interactive", "automated", "pipeline", "network", "ratings" describe a candidate's
# work well, but in a JD they mostly appear in generic prose ("sales pipeline",
# "our network of partners", "interactive onboarding").
JD_CAPABILITY_PATTERNS = {
    'frontend_ui': [r'\bfront[- ]?end\b', r'\buser interfaces?\b', r'\bui\s*/\s*ux\b', r'\bui\b',
                    r'\b(?:web|mobile) (?:app|application)s?\b',
                    r'\b(?:react(?:\.js)?|javascript|typescript|html|css|angular|vue(?:\.js)?)\b',
                    r'\bfull[- ]stack\b', r'\bweb development\b'],
    'backend_api': [r'\bback[- ]?end\b', r'\bapis?\b', r'\brestful\b', r'\bserver[- ]side\b',
                    r'\bmicroservices?\b', r'\bdatabases?\b', r'\bsql\b', r'\bfull[- ]stack\b',
                    r'\bdistributed (?:systems?|ledger)\b', r'\b(?:aws|gcp|azure)\b',
                    r'\b(?:kubernetes|docker)\b', r'\binternal tool(?:s|ing)?\b'],
    'agent_llm': [r'\bai agents?\b', r'\bagentic\b', r'\bllms?\b', r'\blarge language models?\b',
                  r'\bgenerative ai\b', r'\bgen ?ai\b', r'\bopenai\b', r'\bprompt engineering\b',
                  r'\bretrieval[- ]augmented\b', r'\brag\b'],
    'data_ml': [r'\bdata anal\w*\b', r'\bdata scien\w*\b', r'\bdata mining\b', r'\bmachine learning\b',
                r'\bdeep learning\b', r'\bstatistic\w*\b', r'\banalytics\b', r'\bdashboards?\b',
                r'\b(?:power bi|tableau|pandas|numpy|scikit[- ]learn)\b', r'\brecommend\w* (?:systems?|engines?)\b',
                r'\bnlp\b|\bnatural language processing\b', r'\bpredictive model\w*\b', r'\ba/b test\w*\b'],
    'systems': [r'\bc\+\+', r'\boperating systems?\b', r'\bembedded\b', r'\blow[- ]level\b',
                r'\bcompilers?\b', r'\bparsers?\b', r'\bnetwork protocols?\b', r'\blinux\b',
                r'\bmemory management\b', r'\bmulti-?thread\w*\b', r'\bconcurren\w*\b',
                r'\blow[- ]latency\b', r'\bsystems programming\b', r'\bfpgas?\b', r'\bhardware acceleration\b',
                r'\bbare[- ]metal\b', r'\b(?:performance|low-level) optimi[sz]ation\b'],
    'user_product': [r'\buser[- ]facing\b', r'\bcustomer[- ]facing\b', r'\bproduct features?\b',
                     r'\bend[- ]users?\b', r'\buser experience\b', r'\bux\b', r'\bbooking\b',
                     r'\bmobile apps?\b'],
}
JD_CAPS = {k: [re.compile(p, re.I) for p in patterns] for k, patterns in JD_CAPABILITY_PATTERNS.items()}


def detect_skills(text: str) -> set[str]:
    return {name for name, regex in REGEX.items() if regex.search(text)}


def detect_capabilities(text: str) -> set[str]:
    return {name for name, patterns in CAPS.items() if any(p.search(text) for p in patterns)}


def segment_jd(jd_text: str) -> list[tuple[str, str]]:
    """Label each JD line: required / preferred / responsibilities / mentioned / boilerplate.

    A line switches the active section only when it looks like a heading
    (short), so "Requirements gathering with stakeholders..." stays content.
    """
    rows: list[tuple[str, str]] = []
    active = 'mentioned'
    for line in jd_text.splitlines():
        bulleted = bool(re.match(r'^\s*[*•\-]', line))
        stripped = re.sub(r'^[#\s*•\-]+', '', line).strip()
        if not stripped:
            continue
        if len(stripped) <= 70:
            if REQUIRED_HEADERS.match(stripped):
                active = 'required'
            elif PREFERRED_HEADERS.match(stripped):
                active = 'preferred'
            elif RESPONSIBILITY_HEADERS.match(stripped):
                active = 'responsibilities'
            elif BOILERPLATE_HEADERS.match(stripped):
                active = 'boilerplate'
            elif COMPANY_HEADERS.match(stripped):
                active = 'company'
            elif active in ('boilerplate', 'company') and not bulleted and _looks_like_heading(stripped):
                # v0.5.1: an unknown heading ("Who this is for", "The Challenge")
                # ends a company/benefits block, so it cannot swallow the whole JD.
                active = 'mentioned'
        if len(stripped) <= 110 and WORK_INTRO.search(stripped):
            active = 'responsibilities'  # "During your internship, you will work on..."
        rows.append((active, stripped))
    return rows


def _looks_like_heading(text: str) -> bool:
    words = text.split()
    first_alpha = next((ch for ch in text if ch.isalpha()), '')
    return (len(text) <= 60 and 1 <= len(words) <= 8 and first_alpha.isupper()
            and not re.search(r'[.,;!?]$', text) and not re.search(r'[\d£$€%]', text))


def jd_signal(jd_text: str) -> float:
    """Strongest raw role-family score; below WEAK_JD_SIGNAL the JD can't steer selection."""
    raw = {k: 0.0 for k in JD_CAPS}
    for section, line in segment_jd(jd_text):
        weight = SECTION_WEIGHT[section]
        for family, patterns in JD_CAPS.items():
            raw[family] += weight * sum(1 for p in patterns if p.search(line))
    return max(raw.values())


def parse_jd(jd_text: str) -> dict[str, list[str]]:
    groups: dict[str, set[str]] = {'required': set(), 'preferred': set(), 'mentioned': set()}
    for section, line in segment_jd(jd_text):
        if section == 'boilerplate':
            continue
        key = section if section in ('required', 'preferred') else 'mentioned'
        groups[key] |= detect_skills(line)
    groups['preferred'] -= groups['required']
    groups['mentioned'] -= groups['required'] | groups['preferred']
    return {key: sorted(value) for key, value in groups.items()}


def job_priorities(jd_text: str, jd: dict[str, list[str]] | None = None) -> dict[str, float]:
    """Graded RESPONSIBILITY-family weights in [0, 1]; never a candidate skill claim.

    raw[family] = sum over JD lines of (section weight x distinct patterns hit).
    Weights are relative to the strongest family; families under 15% of it are 0.
    """
    raw = {k: 0.0 for k in JD_CAPS}
    for section, line in segment_jd(jd_text):
        weight = SECTION_WEIGHT[section]
        if not weight:
            continue
        for family, patterns in JD_CAPS.items():
            hits = sum(1 for p in patterns if p.search(line))
            raw[family] += weight * hits
    top = max(raw.values())
    if top <= 0:
        weights = {k: 0.0 for k in JD_CAPS}
        weights['backend_api'] = .25  # conservative fallback for generic software jobs
        return weights
    weights = {k: round(v / top, 2) for k, v in raw.items()}
    return {k: (v if v >= .15 else 0.0) for k, v in weights.items()}


def score_bullet(bullet_text: str, jd: dict[str, list[str]],
                 priorities: dict[str, float] | None = None) -> tuple[float, list[str]]:
    found = detect_skills(bullet_text)
    req = found & set(jd['required'])
    pref = found & set(jd['preferred'])
    mentioned = found & set(jd['mentioned'])
    # Cap named-skill points, so Python + API doesn't automatically beat real UI work.
    score = 2.0 + min(2, len(req)) * 5.5 + min(2, len(pref)) * 3.0 + min(2, len(mentioned)) * 1.5
    why = []
    if req: why.append('required skill: ' + ', '.join(sorted(req)))
    if pref: why.append('preferred skill: ' + ', '.join(sorted(pref)))
    if mentioned: why.append('JD mentions: ' + ', '.join(sorted(mentioned)))
    priorities = priorities or {}
    evidence_caps = detect_capabilities(bullet_text)
    related = [(k, priorities.get(k, 0.0)) for k in evidence_caps if priorities.get(k, 0.0) > 0]
    # Distinct capability groups receive credit, but max out to avoid keyword stuffing.
    capability_score = min(14.0, sum(8.0 * value for _, value in related))
    score += capability_score
    if related: why.append('role responsibility evidence: ' + ', '.join(sorted(k for k, _ in related)))
    # Only small bonuses for numbers and generic verbs: measurable != role-aligned.
    if re.search(r'\b\d[\d,.]*%?\b', bullet_text):
        score += 0.75
        why.append('quantified result (small bonus)')
    if re.match(r'^(built|developed|implemented|designed|integrated|created|automated|benchmarked|tested|debugged|processed|optimized|trained|deployed)\b', bullet_text, re.I):
        score += 0.75
    if not why: why.append('general experience; no identified role overlap')
    return round(score, 2), why


def _role_alignment(entry: dict[str, Any], priorities: dict[str, float]) -> float:
    text = ' '.join([entry['title'], entry['role']] + [b['text'] for b in entry['bullets']])
    caps = detect_capabilities(text)
    job_keys = {k for k, val in priorities.items() if val >= .5}
    # Relative share of required role families demonstrated by the entire entry.
    # If an entry is mostly analytics, a full-stack vacancy shouldn't give it 3 bullets.
    if not job_keys:
        return 0.5
    return sum(priorities[k] for k in caps & job_keys) / sum(priorities[k] for k in job_keys)


def _entry_score(entry: dict[str, Any], bullets: list[dict[str, Any]],
                 priorities: dict[str, float]) -> float:
    top = sorted((b['score'] for b in bullets), reverse=True)[:2]
    alignment = _role_alignment(entry, priorities)
    # Employment signal is a tiebreaker only; it must not override responsibilities.
    bonus = 1.0 if entry['kind'] == 'internship' else 0.0
    return round(sum(top) / max(1, len(top)) + alignment * 8.0 + bonus, 2)


def _novelty(bullet: dict[str, Any], chosen: list[dict[str, Any]]) -> float:
    """Penalize repetitive bullets (e.g. two nearly identical UI sentences)."""
    def tokens(txt: str) -> set[str]:
        return set(re.findall(r'[a-z]{4,}', txt.lower())) - {'developed', 'implemented', 'designed', 'using', 'support', 'related', 'based'}
    words = tokens(bullet['text'])
    if not chosen or not words:
        return 0.0
    similarity = max(len(words & tokens(b['text'])) / max(1, len(words | tokens(b['text']))) for b in chosen)
    return similarity * 8.0


# ---------------------------------------------------------------------------
# chunk-v0.5: page-budget selection
# ---------------------------------------------------------------------------
TECH_KINDS = {'internship', 'projects', 'research'}
FILL_KINDS = {'leadership', 'awards'}
PAGE_MAX_BULLETS_PER_ENTRY = 4
SOFT_CAP_OFF_DOMAIN = 2       # bullets for a low-alignment project before activities
RELEVANCE_MIN_MARGINAL = 5.0
# Lower rank = dropped first when the page overflows.
PHASE_RANK = {'activity': 0, 'refill': 1, 'fill': 2, 'relevance': 3, 'anchor': 4}


def _score_reports(master: dict[str, Any], jd_text: str):
    jd = parse_jd(jd_text)
    priorities = job_priorities(jd_text, jd)
    reports = []
    for entry in master['entries']:
        alignment = _role_alignment(entry, priorities)
        bs = []
        for b in entry['bullets']:
            s, reason = score_bullet(b['text'], jd, priorities)
            bs.append({'id': b['id'], 'text': b['text'], 'score': s,
                       'reasons': reason, 'paragraph': b['paragraph']})
        reports.append({'id': entry['id'], 'title': entry['title'], 'role': entry['role'],
                        'kind': entry['kind'], 'score': _entry_score(entry, bs, priorities),
                        'alignment': round(alignment, 3), 'bullets': bs})
    return jd, priorities, reports


def _alignment_cap(alignment: float, limit: int) -> int:
    if alignment < 0.35:
        return min(limit, 1)
    if alignment < 0.55:
        return min(limit, 2)
    return limit


def fill_page(master: dict[str, Any], jd_text: str, page_model, *,
              chosen: dict[str, list[str]] | None = None,
              texts: dict[str, str] | None = None,
              excluded_ids: set[str] | frozenset = frozenset(),
              budget_pt: float | None = None,
              max_bullets_per_entry: int = PAGE_MAX_BULLETS_PER_ENTRY,
              allow_activity_fill: bool = True,
              phases: tuple[str, ...] = ('anchor', 'relevance', 'fill', 'activity'),
              label: str | None = None) -> tuple[dict[str, list[str]], list[dict]]:
    """Greedily add whole, original bullets until the estimated page is full.

    chosen:       {entry_id: [bullet_id, ...]} already on the page (kept as is)
    texts:        final text for chosen bullets (merged / rewritten), for height
    excluded_ids: bullets that must never be added (e.g. absorbed into a merge)
    Returns (chosen, log); log rows record phase, value and cost of each addition.
    """
    _, _, reports = _score_reports(master, jd_text)
    by_entry = {r['id']: r for r in reports}
    bullet_obj = {b['id']: b for e in master['entries'] for b in e['bullets']}
    chosen = {k: list(v) for k, v in (chosen or {}).items() if v}
    texts = dict(texts or {})
    budget = page_model.budget_pt() if budget_pt is None else budget_pt
    log: list[dict] = []

    def plan_rows(state):
        return {eid: [(bullet_obj[b], texts.get(b, bullet_obj[b]['text'])) for b in ids]
                for eid, ids in state.items()}

    def used(state):
        return page_model.plan_pt(plan_rows(state))

    taken = lambda: {b for ids in chosen.values() for b in ids} | set(excluded_ids)

    def proposals(kinds, capped, threshold):
        out = []
        current = used(chosen)
        blocked = taken()
        for report in reports:
            if report['kind'] not in kinds:
                continue
            eid = report['id']
            have = chosen.get(eid, [])
            if capped == 'soft':
                # Off-domain projects get 2 bullets before activities get a turn;
                # the internship is never capped here (employment credibility).
                limit = max_bullets_per_entry
                if report['kind'] != 'internship' and report['alignment'] < 0.35:
                    limit = min(limit, SOFT_CAP_OFF_DOMAIN)
            elif capped:
                limit = _alignment_cap(report['alignment'], max_bullets_per_entry)
            else:
                limit = max_bullets_per_entry
            if len(have) >= limit:
                continue
            avail = [b for b in report['bullets'] if b['id'] not in blocked]
            if not avail:
                continue
            chosen_objs = [{'text': texts.get(x, bullet_obj[x]['text'])} for x in have]
            def marginal(b):
                value = b['score'] - _novelty(b, chosen_objs) + report['alignment'] * 7.0
                if len(have) >= 2:
                    value -= 4.0  # third+ bullet in one entry needs stronger evidence
                if not have and report['kind'] == 'internship':
                    value += 1.0
                return value
            if report['kind'] in FILL_KINDS:
                # Activities/awards: their first bullet usually names the project or
                # role ("Co-developed an EMG-based knee brace..."), so keep master order.
                best = min(avail, key=lambda b: b['paragraph'])
            else:
                best = max(avail, key=lambda b: (marginal(b), -b['paragraph']))
            value = marginal(best)
            if value < threshold:
                continue
            trial = {k: list(v) for k, v in chosen.items()}
            trial.setdefault(eid, []).append(best['id'])
            cost = used(trial) - current
            if used(trial) <= budget:
                out.append((value, -best['paragraph'], eid, best['id'], cost))
        return out

    def run(phase, kinds, capped, threshold, once=False):
        while True:
            options = proposals(kinds, capped, threshold)
            if not options:
                return
            value, _, eid, bid, cost = max(options)
            chosen.setdefault(eid, []).append(bid)
            log.append({'bullet_id': bid, 'entry_id': eid, 'phase': label or phase,
                        'value': round(value, 2), 'cost_pt': round(cost, 1)})
            if once:
                return

    if 'anchor' in phases:
        internships = [r for r in reports if r['kind'] == 'internship']
        if internships and not any(by_entry[e]['kind'] == 'internship' for e in chosen if e in by_entry):
            run('anchor', {'internship'}, capped=False, threshold=float('-inf'), once=True)
    if 'relevance' in phases:
        run('relevance', TECH_KINDS, capped=True, threshold=RELEVANCE_MIN_MARGINAL)
    if 'fill' in phases:
        run('fill', TECH_KINDS, capped='soft', threshold=float('-inf'))
    if 'activity' in phases and allow_activity_fill:
        run('activity', FILL_KINDS, capped=False, threshold=float('-inf'))
    if 'fill' in phases:  # any space still left goes back to technical bullets
        run('fill', TECH_KINDS, capped=False, threshold=float('-inf'))
    for eid in chosen:  # keep master order inside each entry
        chosen[eid].sort(key=lambda b: bullet_obj[b]['paragraph'])
    return chosen, log


def drop_lowest(chosen: dict[str, list[str]], values: dict[str, dict],
                protect: set[str] = frozenset()) -> str | None:
    """Remove the least valuable bullet (activity/refill/fill before relevance)."""
    candidates = [(PHASE_RANK.get(values.get(b, {}).get('phase'), 3), values.get(b, {}).get('value', 0.0), b, eid)
                  for eid, ids in chosen.items() for b in ids if b not in protect]
    if not candidates:
        return None
    _, _, bid, eid = min(candidates)
    chosen[eid].remove(bid)
    if not chosen[eid]:
        del chosen[eid]
    return bid


def _select_for_page(master: dict[str, Any], jd_text: str, page_model, *,
                     max_bullets_per_entry: int, allow_activity_fill: bool) -> dict[str, Any]:
    jd, priorities, reports = _score_reports(master, jd_text)
    signal = jd_signal(jd_text)
    weak = signal < WEAK_JD_SIGNAL
    # A weak JD gives no real relevance ranking; don't label anything "relevant".
    phases = ('anchor', 'fill', 'activity') if weak else ('anchor', 'relevance', 'fill', 'activity')
    chosen, log = fill_page(master, jd_text, page_model, phases=phases,
                            max_bullets_per_entry=max_bullets_per_entry,
                            allow_activity_fill=allow_activity_fill)
    values = {row['bullet_id']: {'phase': row['phase'], 'value': row['value']} for row in log}
    sel_bids = {b for ids in chosen.values() for b in ids}
    sel_ids = set(chosen)
    bullet_obj = {b['id']: b for e in master['entries'] for b in e['bullets']}
    used_pt = page_model.plan_pt({e: [(bullet_obj[b], bullet_obj[b]['text']) for b in ids]
                                  for e, ids in chosen.items()})
    phase_text = {'anchor': 'kept as credible internship history', 'relevance': 'selected for JD relevance',
                  'fill': 'added to use remaining page space', 'activity': 'activity/award added to use remaining page space'}
    for entry in reports:
        entry['selected'] = entry['id'] in sel_ids
        entry['selected_bullets'] = sum(b['id'] in sel_bids for b in entry['bullets'])
        for b in entry['bullets']:
            b['selected'] = b['id'] in sel_bids
            if b['selected']:
                b['phase'] = values[b['id']]['phase']
                b['reasons'] = b['reasons'] + [phase_text[b['phase']]]
            else:
                b['reasons'] = b['reasons'] + ['did not fit the one-page budget at its value']
    source_text = '\n'.join(x['text'] for x in master.get('skills', []) + master.get('education', []))
    source_text += '\n' + '\n'.join(b['text'] for e in master['entries'] for b in e['bullets'])
    missing = sorted(set(jd['required']) - detect_skills(source_text))
    budget = page_model.budget_pt()
    return {'schema_version': 3, 'source_file': master['source_file'],
            'source_sha256': master['source_sha256'], 'jd_skills': jd,
            'jd_role_priorities': priorities, 'required_not_evidenced_in_resume': missing,
            'selected_entry_ids': sorted(sel_ids), 'selected_bullet_ids': sorted(sel_bids),
            'entries': reports, 'warnings': list(master.get('warnings', [])),
            'page_plan': {'mode': 'page', 'usable_pt': round(page_model.usable_pt, 1),
                          'fixed_pt': round(page_model.fixed_pt, 1), 'budget_pt': round(budget, 1),
                          'used_pt': round(used_pt, 1), 'remaining_pt': round(budget - used_pt, 1),
                          'line_pt': 12.65, 'jd_signal': round(signal, 2),
                          'jd_signal_weak': weak, 'values': values, 'log': log},
            'notes': ['Scores are internal heuristics, not ATS or hiring predictions.',
                      'Page mode fills one page by ESTIMATED height; confirm pagination in Word.',
                      'Relevant technical bullets are chosen first; remaining space then takes other '
                      'technical bullets, and only then leadership/awards.',
                      'Bullet wording is preserved exactly; no skills or results are invented.',
                      'Unavailable skills are not necessarily absent; verify personally.']}


def select_chunks(master: dict[str, Any], jd_text: str, *,
                  max_entries: int = 4, max_bullets: int = 8,
                  max_bullets_per_entry: int = 3,
                  include_leadership: bool = False,
                  page_budget=None,
                  page_max_bullets_per_entry: int = PAGE_MAX_BULLETS_PER_ENTRY,
                  allow_activity_fill: bool = True) -> dict[str, Any]:
    """Legacy fixed-count selection, or (chunk-v0.5) one-page selection.

    page_budget: a resume_layout.PageModel. When given, max_entries / max_bullets /
    include_leadership are ignored and the page is filled by estimated height.
    """
    if page_budget is not None:
        return _select_for_page(master, jd_text, page_budget,
                                max_bullets_per_entry=page_max_bullets_per_entry,
                                allow_activity_fill=allow_activity_fill)
    if min(max_entries, max_bullets, max_bullets_per_entry) < 1:
        raise ValueError('All budgets must be >= 1.')
    jd = parse_jd(jd_text)
    priorities = job_priorities(jd_text, jd)
    reports = []
    lookup: dict[str, dict[str, Any]] = {}
    for entry in master['entries']:
        alignment = _role_alignment(entry, priorities)
        bs = []
        for b in entry['bullets']:
            s, reason = score_bullet(b['text'], jd, priorities)
            bs.append({'id': b['id'], 'text': b['text'], 'score': s,
                       'reasons': reason, 'paragraph': b['paragraph']})
        row = {'id': entry['id'], 'title': entry['title'], 'role': entry['role'],
               'kind': entry['kind'], 'score': _entry_score(entry, bs, priorities),
               'alignment': round(alignment, 3), 'bullets': bs}
        lookup[row['id']] = row
        reports.append(row)

    candidate_types = {'internship', 'projects', 'research'} | ({'leadership', 'awards'} if include_leadership else set())
    candidates = [x for x in reports if x['kind'] in candidate_types and x['bullets']]
    candidates.sort(key=lambda e: (-e['score'], e['id']))
    selected = candidates[:max_entries]
    # Preserve at least one real internship as credible employment history when budget allows.
    internships = [x for x in candidates if x['kind'] == 'internship']
    if internships and selected and not any(x['kind'] == 'internship' for x in selected):
        selected[-1] = internships[0]
    if len(selected) > max_bullets:
        selected = selected[:max_bullets]
    # Stable presentation follows master document order rather than arbitrary scores.
    sel_ids = {e['id'] for e in selected}
    selected_bids = set()
    chosen_by_entry = {e['id']: [] for e in selected}
    for entry in selected:
        b = max(entry['bullets'], key=lambda x: (x['score'], -x['paragraph']))
        selected_bids.add(b['id'])
        chosen_by_entry[entry['id']].append(b)

    # A mostly off-domain entry remains as 1 bullet; a closer role match gets space.
    def cap(entry):
        limit = max_bullets_per_entry
        # Role alignment 0 for data analytics when applying frontend/AI product:
        # evidence remains, but not at the expense of frontend details.
        if entry['alignment'] < 0.35:
            limit = min(limit, 1)
        elif entry['alignment'] < 0.55:
            limit = min(limit, 2)
        return limit

    # First consider giving highly aligned projects a second bullet before anyone's third.
    # Then allocate remaining slots by marginal relevance + diversity.
    for round_number in range(2, max_bullets_per_entry + 1):
        while len(selected_bids) < max_bullets:
            proposals = []
            for entry in selected:
                chosen = chosen_by_entry[entry['id']]
                if len(chosen) != round_number - 1 or len(chosen) >= cap(entry):
                    continue
                available = [b for b in entry['bullets'] if b['id'] not in selected_bids]
                if not available:
                    continue
                best = max(available, key=lambda b: (b['score'] - _novelty(b, chosen), -b['paragraph']))
                marginal = best['score'] - _novelty(best, chosen)
                marginal += entry['alignment'] * 7.0
                # Reduce concentration: after second bullet, demand stronger evidence.
                if round_number >= 3:
                    marginal -= 4.0
                proposals.append((marginal, -best['paragraph'], entry['id'], best))
            if not proposals:
                break
            marginal, _, entry_id, best = max(proposals, key=lambda p: (p[0], p[1], p[2]))
            if marginal < 5:
                break
            selected_bids.add(best['id'])
            chosen_by_entry[entry_id].append(best)
        if len(selected_bids) >= max_bullets:
            break

    for entry in reports:
        entry['selected'] = entry['id'] in sel_ids
        entry['selected_bullets'] = sum(b['id'] in selected_bids for b in entry['bullets'])
        for b in entry['bullets']:
            b['selected'] = b['id'] in selected_bids
            if not b['selected'] and entry['selected']:
                b['reasons'] = b['reasons'] + ['space, role alignment, or redundancy budget']

    source_text = '\n'.join(x['text'] for x in master.get('skills', []) + master.get('education', []))
    source_text += '\n' + '\n'.join(b['text'] for e in master['entries'] for b in e['bullets'])
    missing = sorted(set(jd['required']) - detect_skills(source_text))
    return {'schema_version': 2, 'source_file': master['source_file'],
            'source_sha256': master['source_sha256'], 'jd_skills': jd,
            'jd_role_priorities': priorities, 'required_not_evidenced_in_resume': missing,
            'selected_entry_ids': sorted(sel_ids), 'selected_bullet_ids': sorted(selected_bids),
            'entries': reports, 'warnings': list(master.get('warnings', [])),
            'notes': ['Scores are internal heuristics, not ATS or hiring predictions.',
                      'Role responsibilities count even when the bullet lacks exact JD keywords.',
                      'Quantitative results do not automatically outrank direct engineering work.',
                      'Bullet wording is preserved exactly; no skills or results are invented.',
                      'Unavailable skills are not necessarily absent; verify personally.',
                      'The final Word layout, dates and numerical claims require human review.']}


def export_report(selection: dict[str, Any], output: str | Path) -> None:
    lines = ['# Resume Chunk Selection Report (chunk-v0.5)', '',
             f'**Source:** `{selection["source_file"]}`', '']
    plan = selection.get('page_plan')
    if plan:
        lp = plan.get('line_pt', 12.65)
        if plan.get('jd_signal_weak'):
            lines += ['> **JD signal too weak to tailor** (score '
                      f'{plan.get("jd_signal")} < {WEAK_JD_SIGNAL}): no recognised role keywords. '
                      'The page is filled by general value only — check that the JD text was extracted '
                      'correctly, or choose bullets manually.', '']
        lines += ['## Page plan (estimated)', '',
                  f'- Usable page height: {plan["usable_pt"]}pt; fixed header/education/skills: {plan["fixed_pt"]}pt',
                  f'- Budget for experience sections: {plan["budget_pt"]}pt; used: {plan["used_pt"]}pt; '
                  f'remaining: {plan["remaining_pt"]}pt (~{plan["remaining_pt"] / lp:.1f} lines)', '']
    lines += ['## JD skill extraction', '']
    for k, v in selection['jd_skills'].items():
        lines.append(f'- {k}: {", ".join(v) if v else "(none identified)"}')
    lines += ['', '## Role responsibility weights', '']
    lines += [f'- {k}: {v:g}' for k, v in selection['jd_role_priorities'].items() if v > 0]
    missing = selection['required_not_evidenced_in_resume']
    lines += ['', '**Required skills not evidenced in this resume:** ' + (', '.join(missing) if missing else 'None detected'),
              '', '## Entry / bullet selection', '']
    for e in sorted(selection['entries'], key=lambda x: (-x['score'], x['title'])):
        status = 'KEEP' if e['selected'] else 'OMIT'
        lines += [f'### [{status}] {e["title"]} — entry score {e["score"]}, role alignment {e["alignment"]:.2f}, bullets {e["selected_bullets"]}', '']
        for b in e['bullets']:
            tag = 'KEEP' if b['selected'] else 'omit'
            if b.get('phase'):
                tag += ' · ' + b['phase']
            lines.append(f'- [{tag} / {b["score"]:.2f}] {b["text"]}')
            lines.append('  - Reason: ' + '; '.join(b['reasons']))
        lines.append('')
    lines += ['## Caveats', ''] + [f'- {n}' for n in selection['notes']]
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def render_selected_docx(master_file: str | Path, master: dict[str, Any],
                         selection: dict[str, Any], output_file: str | Path,
                         bullet_replacements: dict[str, str] | None = None) -> None:
    """Remove unselected paragraphs from a COPY; preserve master wording and facts.

    Add visible vertical spacing between *different entry chunks* inside a
    section without allowing title/role to split across pages.
    """
    from docx import Document
    from docx.shared import Pt
    source = Path(master_file)
    if hashlib.sha256(source.read_bytes()).hexdigest() != master['source_sha256']:
        raise ValueError('Master DOCX changed after parsing. Re-parse before rendering.')
    if master['source_sha256'] != selection['source_sha256']:
        raise ValueError('Selection belongs to a different master resume.')
    doc = Document(str(source))
    paragraphs = doc.paragraphs
    # Rewrites are restricted to the selected, source-linked bullet IDs. Headers,
    # education, skills, employers, roles and dates are never editable here.
    replacements = bullet_replacements or {}
    valid_ids = set(selection['selected_bullet_ids'])
    if not isinstance(replacements, dict) or not set(replacements).issubset(valid_ids):
        raise ValueError('Bullet rewrite attempted to touch a non-selected/unknown ID.')
    bullet_index = {b['id']: b for e in master['entries'] for b in e['bullets']}
    for bullet_id, rewritten in replacements.items():
        if not isinstance(rewritten, str) or not rewritten.strip():
            raise ValueError('Empty or invalid bullet replacement.')
        para = paragraphs[bullet_index[bullet_id]['paragraph']]
        if not para.runs:
            raise ValueError('Unexpected bullet without text runs.')
        # Preserve numbering/indentation and run formatting; do not replace para.text.
        runs = list(para.runs)
        first = next((run for run in runs if run.text), runs[0])
        first.text = rewritten.strip()
        for run in runs:
            if run._r is not first._r:
                run.text = '' 
    to_remove: set[int] = set()
    kept_entries = set(selection['selected_entry_ids'])
    kept_bullets = set(selection['selected_bullet_ids'])
    for entry in master['entries']:
        if entry['id'] not in kept_entries:
            to_remove.add(entry['title_paragraph'])
            if entry['role_paragraph'] is not None:
                to_remove.add(entry['role_paragraph'])
        for bullet in entry['bullets']:
            if entry['id'] not in kept_entries or bullet['id'] not in kept_bullets:
                to_remove.add(bullet['paragraph'])
    for heading in master['section_headings']:
        if heading['section'] in ('education', 'skills'):
            continue
        if not any(e['source_section'] == heading['section'] and e['id'] in kept_entries for e in master['entries']):
            to_remove.add(heading['paragraph'])
    # Avoid preserving arbitrary blank lines after removal; provide deliberate
    # consistent entry separation via paragraph_format.space_before.
    for idx, p in enumerate(paragraphs):
        if not p.text.strip():
            to_remove.add(idx)
    # Titles are already separate paragraphs; enforce a clearly visible gap
    # whenever a new subchunk follows another entry in the same major section.
    previous_section = None
    for entry in master['entries']:
        if entry['id'] not in kept_entries:
            continue
        p = paragraphs[entry['title_paragraph']]
        p.paragraph_format.space_before = Pt(7 if previous_section == entry['source_section'] else 2)
        p.paragraph_format.keep_with_next = False
        p.paragraph_format.keep_together = False
        if entry['role_paragraph'] is not None:
            paragraphs[entry['role_paragraph']].paragraph_format.keep_with_next = False
            paragraphs[entry['role_paragraph']].paragraph_format.keep_together = False
        previous_section = entry['source_section']
    for idx in sorted(to_remove, reverse=True):
        el = paragraphs[idx]._element
        el.getparent().remove(el)
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    if hashlib.sha256(source.read_bytes()).hexdigest() != master['source_sha256']:
        raise AssertionError('Source file was unexpectedly modified.')
