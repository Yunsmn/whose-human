# Member A paper draft

This is a pre-results draft for the introduction, threat model, and ethics sections. Convert the prose and
author-year references to the paper's ACM LaTeX and BibTeX conventions when the shared paper scaffold and
bibliography land. Claims about our own system are deliberately written as goals or methods until experiments
produce results.

## Introduction

AI coding agents increasingly act on a developer's behalf: they inspect repositories, invoke tools, and fetch
web pages while solving a task. To a visited site, however, the apparent visitor may be a generic HTTP client
rather than a browser or a named product. The request can still expose a layered signature of the harness,
runtime, TLS implementation, and host environment. When several sites cooperate, those observations may make
the person operating multiple agents linkable even though the person never visits in a conventional browser.

Prior work establishes important pieces of this problem without answering the user-linking question. Borysenko
(2026) reports stable HTTP behaviors for coding agents, while Kang et al. (2026) combine TLS, HTTP/2, and header
features to identify autonomous web agents. Pasquini et al. (2025) show that model-generated text can identify
LLM families. Work on cross-device and behavioral tracking demonstrates that network and behavioral signals can
link people over time (Zimmeck et al., 2017; Bird et al., 2020; Crichton et al., 2025). Existing agent studies,
however, generally target the agent or model as the endpoint. They do not ask whether requests from different
coding agents and cooperating sites can be joined back to one human operator.

We study that gap through three questions. First, can an instrumented site identify the coding-agent harness and
distinguish it from an ordinary script using the same HTTP library? Second, can short text that an agent visibly
submits identify the model provider, and does the harness shift that text relative to direct API output? Third,
can cooperating sites link requests made by different agents to the same consenting participant, including links
to that participant's browser and settings in which the network address changes?

The study contributes a consent-based measurement setup for local coding agents, a layered harness baseline, a
short-text model-attribution experiment, and a user-linking evaluation across agents and sites. The evaluation
separates the obvious IP baseline from transport and runtime environment signatures. It also measures failure
cases: shared network addresses, identical software configurations, and changed networks. These contributions
must be revised into result statements only after the preregistered runs are complete.

## Threat model

The adversary is a small network of cooperating websites that the participant or their locally running coding
agent intentionally visits. Each site terminates TLS itself and records ordinary server-side observations: peer
address, TLS ClientHello, negotiated protocol, ordered HTTP headers, HTTP/2 settings, request sequence, and
coarse timing. Sites may share those observations and compare them with visits to the other partner sites. A
site may display a plain-language task asking the agent to summarize visible text and submit the answer. If the
agent complies, the adversary receives that text through a normal GET or POST request.

The adversary's first goal is harness attribution: estimate which agent produced a request and distinguish that
agent from a plain client using the same library. Its second goal is probabilistic model attribution from
submitted text. Its final goal is user linkage: decide whether two requests belong to the same participant when
the harness or partner site differs, and measure whether the linkage survives a network change. The study treats
IP equality as a baseline rather than evidence of a novel fingerprint.

The adversary does not control the participant's device, agent, model provider, network, or third-party sites. It
does not read local files, intercept unrelated traffic, exploit software, inject hidden instructions, or compel
an agent to disclose state. It sees no provider-side fetch unless that fetch reaches an instrumented partner
site. Chat-only assistants whose URL retrieval runs on provider infrastructure are outside scope because their
requests generally describe the provider environment rather than the user. Agents shown by the locality check to
fetch remotely are excluded from user-linking experiments and retained only where appropriate for harness
measurement.

The principal assumptions are that the partner sites can share records, ground-truth run labels are accurate,
and each experimental run begins from the documented agent and machine state. The analysis must not treat a
stable agent fingerprint as a stable human identity without testing across agents, sites, machines, and network
conditions.

### Member A machine-level extension

Member A additionally evaluates a narrower claim for locally hosted models: whether an Omen session and a Queen
session probably ran on the same enrolled PC. An ordinary TLS/HTTP request does not reveal CPU, GPU, RAM, token
usage, or local inference duration. The consented experiment therefore adds an optional loopback-only Ollama
collector that runs fixed synthetic prompts and discards prompts and generated text. It retains approximate time
to first streamed chunk, model-reported load and evaluation durations, token counts and throughput, chunk-timing
statistics, and the documented model, engine, and quantization.

Repeated measurements are aggregated into one profile per session. For each profile feature $x_k$, the pairwise
comparison uses the symmetric relative difference

$$d_k(a,b)=\frac{|x_{a,k}-x_{b,k}|}{|x_{a,k}|+|x_{b,k}|+\epsilon}.$$

A regularized logistic model produces a `same_pc_probability` score from these differences and software-match
indicators. Only scores above a threshold fixed on separate validation machines receive `probably_same_pc`;
all other pairs remain `unknown`. Evaluation holds out entire PCs, rather than randomly splitting requests, and
reports precision, recall, F1, ROC-AUC, Brier score, false matches, and false non-matches. This is a performance
fingerprint of an enrolled inference platform, not direct hardware telemetry or proof of a unique physical PC.

## Ethics and data handling

The experiment is restricted to infrastructure operated by the research team. Participants are team members or
volunteers who give informed consent and use fictitious personas. No third-party website is scraped, probed, or
instrumented. Every instruction shown to an agent is visible on the page: the design forbids hidden text, prompt
injection, deceptive overlays, and coercive requests. A failed fetch or refusal to submit is recorded as a valid
outcome rather than bypassed with another tool.

The server necessarily observes network addresses for the locality and IP-baseline experiments. Raw logs are
therefore private research data: they stay in the gitignored data directory or access-controlled team storage
and are never committed to the public repository. Public run manifests contain only pseudonymous persona,
machine, and network-category labels. Reports aggregate locality and collision outcomes and do not print or
publish addresses. Derived environment signatures are also treated as private persistent identifiers even
though they omit IP addresses.

Data collection follows minimization and purpose limitation. Request bodies are capped by the logging schema;
participants submit only summaries of synthetic site text; and the analysis excludes cookies, paths, body text,
and IP addresses from the environment-signature hash. Access should be limited to the research team, with raw
logs deleted after grading and any required retention period. Volunteers may stop participation and request
deletion of their runs before aggregation.

This is an offensive-track measurement study because it evaluates how cooperating sites could re-identify a
person behind several agents. The implementation remains non-deceptive and confined to a controlled testbed.
The paper should disclose negative and collision results, distinguish inference from observation, and discuss
defenses such as provider-side fetching, fingerprint normalization, network separation, and limits on durable
cross-site identifiers.
