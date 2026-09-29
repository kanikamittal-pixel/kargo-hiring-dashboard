// Kargo Hiring Dashboard -- plain JS frontend calling the Flask API under /api.

let RUBRICS = null;

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const msg = (data && data.error) || `Request failed (${res.status})`;
    toast(msg, "error");
    throw new Error(msg);
  }
  return data;
}

function toast(message, kind = "info") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  document.getElementById("toast-container").appendChild(el);
  setTimeout(() => el.remove(), 6000);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined) continue; // e.g. `disabled: cond ? "true" : undefined` must omit the attribute entirely
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

// ---------- Tabs ----------

function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      loadTab(btn.dataset.tab);
    });
  });
}

function loadTab(name) {
  if (name === "upload") renderUpload();
  else if (name === "score") renderScore();
  else if (name === "shortlist") renderBandTab("shortlist", "SHORTLIST");
  else if (name === "review") renderBandTab("review", "REVIEW");
  else if (name === "autoreject") renderAutoRejectLog();
  else if (name === "decisionlog") renderDecisionLog();
  else if (name === "allcandidates") renderAllCandidates();
}

// ---------- Upload ----------

function renderUpload() {
  const root = document.getElementById("tab-upload");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Bulk upload CVs"));

  const roleSelect = el("select", {}, [
    el("option", { value: "PM" }, "PM"),
    el("option", { value: "SPM" }, "SPM"),
  ]);
  root.appendChild(el("div", { class: "field" }, [
    el("label", {}, "Default applied role for this batch"), roleSelect,
  ]));

  const fileInput = el("input", { type: "file", multiple: "true", accept: ".pdf,.docx" });
  const fileListDiv = el("div", {});
  root.appendChild(el("div", { class: "field" }, [
    el("label", {}, "Upload CVs (PDF or DOCX)"), fileInput, fileListDiv,
  ]));

  const overrides = {};
  fileInput.addEventListener("change", () => {
    fileListDiv.innerHTML = "";
    overrides["_files"] = fileInput.files;
    Array.from(fileInput.files).forEach((f) => {
      const sel = el("select", {}, [
        el("option", { value: "" }, "(use default)"),
        el("option", { value: "PM" }, "PM"),
        el("option", { value: "SPM" }, "SPM"),
      ]);
      sel.addEventListener("change", () => { overrides[f.name] = sel.value; });
      fileListDiv.appendChild(el("div", { class: "file-list-item" }, [el("span", {}, f.name), sel]));
    });
  });

  const resultsDiv = el("div", {});
  const submitBtn = el("button", {
    class: "primary",
    onclick: async () => {
      if (!fileInput.files.length) return;
      submitBtn.disabled = true;
      const fd = new FormData();
      fd.append("default_role", roleSelect.value);
      const cleanOverrides = {};
      for (const [k, v] of Object.entries(overrides)) {
        if (k !== "_files" && v) cleanOverrides[k] = v;
      }
      fd.append("role_overrides", JSON.stringify(cleanOverrides));
      Array.from(fileInput.files).forEach((f) => fd.append("files", f));

      try {
        const data = await api("/api/upload", { method: "POST", body: fd });
        resultsDiv.innerHTML = "";
        resultsDiv.appendChild(el("div", { class: "banner success" }, `Processed ${data.results.length} files.`));
        data.results.forEach((r) => {
          resultsDiv.appendChild(el("div", {}, `${r.filename}: ${r.status}`));
        });
        toast("Batch processed.", "success");
      } finally {
        submitBtn.disabled = false;
      }
    },
  }, "Process batch");
  root.appendChild(submitBtn);
  root.appendChild(resultsDiv);
}

// ---------- Score ----------

async function renderScore() {
  const root = document.getElementById("tab-score");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Score pending candidates"));

  const candidates = await api("/api/candidates");
  const pending = candidates.filter((c) => c.score_status === "not_scored");
  root.appendChild(el("p", {}, `${pending.length} candidate(s) awaiting scoring.`));

  const resultsDiv = el("div", {});
  const btn = el("button", {
    class: "primary",
    disabled: pending.length ? undefined : "true",
    onclick: async () => {
      btn.disabled = true;
      resultsDiv.innerHTML = "";
      resultsDiv.appendChild(el("div", { class: "spinner" }, "Scoring... this calls the LLM once per candidate."));
      try {
        const data = await api("/api/score", { method: "POST" });
        resultsDiv.innerHTML = "";
        resultsDiv.appendChild(el("div", { class: "banner success" }, `Scored ${data.results.length} candidate(s).`));
        data.results.forEach((r) => {
          resultsDiv.appendChild(el("div", {}, `${r.status === "scored" ? "✅" : "⚠️"} ${r.name}: ${r.status} -- ${r.detail}`));
        });
      } finally {
        btn.disabled = false;
      }
    },
  }, "Score all pending candidates");
  root.appendChild(btn);
  root.appendChild(resultsDiv);

  const needsReview = candidates.filter((c) => c.score_status === "needs_manual_review");
  if (needsReview.length) {
    root.appendChild(el("div", { class: "banner warn" }, `${needsReview.length} candidate(s) need manual review.`));
    needsReview.forEach((c) => root.appendChild(el("div", {}, `- ${c.name || c.id} (${c.applied_role})`)));
  }
}

// ---------- Summary bar ----------

function computeSummary(candidates, roleKey) {
  const inRole = candidates.filter((c) => c.final_role === roleKey);
  const needsReview = candidates.filter(
    (c) => c.score_status === "needs_manual_review" && (c.applied_role || "").toLowerCase() === roleKey
  );
  const reasonCounts = {};
  const flagCounts = {};
  inRole.forEach((c) => {
    (c.reason_codes || []).forEach((code) => { reasonCounts[code] = (reasonCounts[code] || 0) + 1; });
    (c.red_flags || []).forEach((f) => { if (f.present) flagCounts[f.id] = (flagCounts[f.id] || 0) + 1; });
  });
  const topOf = (counts) => {
    const entries = Object.entries(counts);
    if (!entries.length) return "-";
    return entries.sort((a, b) => b[1] - a[1])[0][0];
  };
  return {
    shortlist: inRole.filter((c) => c.final_band === "SHORTLIST").length,
    review: inRole.filter((c) => c.final_band === "REVIEW").length,
    auto_reject: inRole.filter((c) => c.final_band === "AUTO_REJECT").length,
    rerouted: inRole.filter((c) => c.reroute_label).length,
    near_miss: inRole.filter((c) => c.final_band_flag === "near miss").length,
    needs_manual_review: needsReview.length,
    most_common_reason_code: topOf(reasonCounts),
    most_common_red_flag: topOf(flagCounts),
  };
}

function renderSummaryBar(container, candidates, roleKey, roleLabel) {
  const s = computeSummary(candidates, roleKey);
  container.appendChild(el("h3", {}, `${roleLabel} summary`));
  const grid = el("div", { class: "summary-bar" });
  [
    ["Shortlist", s.shortlist], ["Review", s.review], ["Auto-reject", s.auto_reject],
    ["Re-routed", s.rerouted], ["Near miss", s.near_miss], ["Needs manual review", s.needs_manual_review],
  ].forEach(([label, num]) => {
    grid.appendChild(el("div", { class: "summary-stat" }, [
      el("div", { class: "num" }, String(num)), el("div", { class: "label" }, label),
    ]));
  });
  container.appendChild(grid);
  container.appendChild(el("div", { class: "summary-caption" },
    `Most common reason code: ${s.most_common_reason_code} · Most common red flag: ${s.most_common_red_flag}`));
}

// ---------- Band reasoning (ported from ui/cards.py) ----------

function bandReasoning(roleKey, score, rubrics) {
  const bandDefs = rubrics.roles[roleKey].bands;
  const shortlistMin = bandDefs.find((b) => b.label === "SHORTLIST").min;
  const reviewMin = bandDefs.find((b) => b.label === "REVIEW" && !b.flag).min;
  const total = score.total_points;
  const band = score.band;
  const bandFlag = score.band_flag;

  if (bandFlag === "above experience range") {
    return "Sent to Review regardless of score: SPM experience is above the 8-year range, so the rubric caps this at Review rather than Shortlist.";
  }

  const sorted = [...score.criteria].sort((a, b) => (a.points / a.weight) - (b.points / b.weight));
  const weakest = sorted[0];
  const strongest = sorted[sorted.length - 1];

  const lines = [];
  if (band === "SHORTLIST") lines.push(`Total ${total} meets the Shortlist threshold (${shortlistMin}+).`);
  else if (bandFlag === "near miss") lines.push(`Total ${total} is within 5 points below the Review threshold (${reviewMin}) -- held as a near miss rather than auto-rejected.`);
  else if (band === "REVIEW") lines.push(`Total ${total} falls in the Review range (below the ${shortlistMin}-point Shortlist bar).`);
  else lines.push(`Total ${total} falls below the auto-reject threshold.`);

  lines.push(`Why not higher: ${weakest.name} (${weakest.id}) scored ${weakest.score}/5 (${weakest.points} of ${weakest.weight} possible points) -- the biggest single drag on the total.`);
  lines.push(`Why not lower: ${strongest.name} (${strongest.id}) scored ${strongest.score}/5, carrying ${strongest.points} of ${strongest.weight} possible points.`);
  return lines.join(" ");
}

// ---------- Candidate card ----------

function criteriaTable(criteria) {
  const table = el("table", {}, [
    el("tr", {}, ["ID", "Criterion", "Anchor", "Score", "Points", "Evidence", "Rationale"].map((h) => el("th", {}, h))),
    ...criteria.map((c) => el("tr", {}, [
      el("td", {}, c.id), el("td", {}, c.name), el("td", {}, String(c.matched_anchor)),
      el("td", {}, String(c.score)), el("td", {}, `${c.points} / ${c.weight}`),
      el("td", {}, c.evidence), el("td", {}, c.rationale),
    ])),
  ]);
  return table;
}

function gatesLine(gates, yearsPm) {
  const parts = [`Years of PM experience (computed): ${yearsPm}`];
  for (const [gid, g] of Object.entries(gates)) {
    let s = `${gid}: ${g.passed ? "PASS" : "FAIL"}`;
    if (g.flag) s += ` -- flagged: ${g.flag}`;
    parts.push(s);
  }
  return el("div", {}, parts.join(" · "));
}

function redFlagsBlock(redFlags, rubrics) {
  const flagDefs = Object.fromEntries(rubrics.red_flags.flags.map((f) => [f.id, f]));
  const present = redFlags.filter((f) => f.present);
  if (!present.length) return el("div", { class: "muted" }, "No red flags.");
  const wrap = el("div", {});
  present.forEach((f) => {
    const fdef = flagDefs[f.id] || {};
    wrap.appendChild(el("div", { class: "banner warn" }, [
      el("strong", {}, `${f.id} -- ${fdef.name || ""}`),
      el("div", {}, `Evidence: ${f.evidence}`),
      el("div", {}, [el("em", {}, `Probe: ${fdef.probe || ""}`)]),
    ]));
  });
  return wrap;
}

function interviewBriefBlock(candidate) {
  if (!candidate.interview_brief_why) {
    return el("div", { class: "muted" }, "Not yet generated. Brief generation ran with scoring -- check the Score tab for errors.");
  }
  const wrap = el("div", {});
  wrap.appendChild(el("div", {}, [el("strong", {}, "Why ranked here: "), candidate.interview_brief_why]));
  wrap.appendChild(el("div", {}, [el("strong", {}, "Biggest gap: "), candidate.interview_brief_gap]));
  const probes = candidate.interview_brief_probes || [];
  if (probes.length) {
    wrap.appendChild(el("h4", {}, "Interview probes"));
    probes.forEach((p) => {
      const tag = p.source === "red_flag" ? "red flag" : "weak criterion";
      wrap.appendChild(el("div", { class: "probe" }, [el("em", {}, p.text), el("span", { class: "tag" }, ` (${tag} ${p.id})`)]));
    });
  }
  return wrap;
}

function emailDraftBlock(candidate, { allowSend = false, onChange } = {}) {
  const wrap = el("div", {});
  if (!candidate.email_body) {
    wrap.appendChild(el("div", { class: "muted" }, "Not yet generated -- drafted automatically when you click Advance or Pass."));
    return wrap;
  }
  if (candidate.resend_message_id) {
    wrap.appendChild(el("div", { class: "banner success" },
      `Sent ${candidate.email_sent_at} -- Resend id ${candidate.resend_message_id}`));
    return wrap;
  }

  const subjectInput = el("input", { type: "text", value: candidate.email_subject });
  const bodyInput = el("textarea", { rows: "10" });
  bodyInput.value = candidate.email_body;

  wrap.appendChild(el("div", { class: "field" }, [el("label", {}, "Subject"), subjectInput]));
  wrap.appendChild(el("div", { class: "field" }, [el("label", {}, "Body"), bodyInput]));

  const actions = el("div", { class: "row-actions" });
  const saveBtn = el("button", {
    onclick: async () => {
      await api(`/api/candidates/${candidate.id}/email`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: subjectInput.value, body: bodyInput.value }),
      });
      toast("Draft saved.", "success");
    },
  }, "Save edits");
  actions.appendChild(saveBtn);

  if (allowSend) {
    const sendBtn = el("button", {
      class: "primary",
      onclick: async () => {
        sendBtn.disabled = true;
        await api(`/api/candidates/${candidate.id}/email`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ subject: subjectInput.value, body: bodyInput.value }),
        });
        try {
          const result = await api(`/api/candidates/${candidate.id}/send`, { method: "POST" });
          toast(`Sent (Resend id: ${result.message_id}).`, "success");
          if (onChange) onChange();
        } finally {
          sendBtn.disabled = false;
        }
      },
    }, "Send");
    actions.appendChild(sendBtn);
  }
  wrap.appendChild(actions);
  return wrap;
}

function candidateCard(candidate, rubrics, scoresCache, onChange) {
  const scores = scoresCache[candidate.id];
  const scoredRole = candidate.final_role;
  const score = scores[scoredRole];
  const otherRole = scoredRole === "pm" ? "spm" : "pm";
  const otherScore = scores[otherRole];

  let title = `${candidate.name || candidate.id} -- ${scoredRole.toUpperCase()} -- ${candidate.final_band}`;
  if (candidate.final_band_flag) title += ` (${candidate.final_band_flag})`;
  if (candidate.reroute_label) title += ` -- ${candidate.reroute_label}`;

  const card = el("div", { class: "card" });
  const header = el("div", { class: "card-header", onclick: () => card.classList.toggle("open") }, [
    el("span", {}, title), el("span", {}, "⌄"),
  ]);
  const body = el("div", { class: "card-body" });

  if (candidate.location_flag_note) {
    body.appendChild(el("div", { class: "banner info" }, `Location: ${candidate.location_flag_note}`));
  }

  if (candidate.better_fit_note) {
    body.appendChild(el("div", { class: "banner warn" }, `Best fit check: ${candidate.better_fit_note}`));
  }

  body.appendChild(el("h4", {}, "Gates"));
  body.appendChild(gatesLine(score.gates, candidate.years_pm_experience));

  body.appendChild(el("h4", {}, "Criteria"));
  body.appendChild(criteriaTable(score.criteria));

  body.appendChild(el("h4", {}, "Red flags"));
  body.appendChild(redFlagsBlock(candidate.red_flags || [], rubrics));

  body.appendChild(el("h4", {}, "Band reasoning"));
  body.appendChild(el("div", {}, bandReasoning(scoredRole, score, rubrics)));

  body.appendChild(el("h4", {}, "Interview brief"));
  body.appendChild(interviewBriefBlock(candidate));

  body.appendChild(el("h4", {}, "Email draft"));
  const emailContainer = el("div", {});
  emailContainer.appendChild(emailDraftBlock(candidate, { allowSend: candidate.decision_status !== "pending", onChange }));
  body.appendChild(emailContainer);

  if (otherScore) {
    const otherCard = el("div", { class: "card" });
    const otherHeader = el("div", { class: "card-header", onclick: () => otherCard.classList.toggle("open") },
      [el("span", {}, `Score on the other rubric (${otherRole.toUpperCase()})`), el("span", {}, "⌄")]);
    const otherBody = el("div", { class: "card-body" }, [
      gatesLine(otherScore.gates, candidate.years_pm_experience),
      criteriaTable(otherScore.criteria),
      el("div", {}, `Total: ${otherScore.total_points} -- ${otherScore.band}`),
    ]);
    otherCard.appendChild(otherHeader);
    otherCard.appendChild(otherBody);
    body.appendChild(otherCard);
  }

  const actions = el("div", { class: "row-actions" });
  const pending = candidate.decision_status === "pending";
  const advanceBtn = el("button", {
    class: "primary",
    disabled: pending ? undefined : "true",
    onclick: async () => {
      advanceBtn.disabled = true;
      try {
        await api(`/api/candidates/${candidate.id}/advance`, { method: "POST" });
        toast("Advanced -- invite drafted.", "success");
        onChange();
      } finally {
        advanceBtn.disabled = false;
      }
    },
  }, "Advance");
  const passBtn = el("button", {
    disabled: pending ? undefined : "true",
    onclick: async () => {
      passBtn.disabled = true;
      try {
        await api(`/api/candidates/${candidate.id}/pass`, { method: "POST" });
        toast("Passed -- rejection drafted.", "success");
        onChange();
      } finally {
        passBtn.disabled = false;
      }
    },
  }, "Pass");
  actions.appendChild(advanceBtn);
  actions.appendChild(passBtn);
  body.appendChild(actions);
  if (!pending) body.appendChild(el("div", { class: "tag" }, `Decision: ${candidate.decision_status}`));

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

// ---------- Shortlist / Review tabs ----------

async function renderBandTab(tabName, band) {
  const root = document.getElementById(`tab-${tabName}`);
  root.innerHTML = "";
  const [rubrics, candidates] = await Promise.all([getRubrics(), api("/api/candidates")]);

  renderSummaryBar(root, candidates, "pm", "PM");
  renderSummaryBar(root, candidates, "spm", "SPM");
  root.appendChild(el("hr"));

  const matching = candidates.filter((c) => c.final_band === band);
  if (!matching.length) {
    root.appendChild(el("div", { class: "banner info" }, `No candidates in ${band} yet.`));
    return;
  }

  const scoresCache = {};
  await Promise.all(matching.map(async (c) => {
    const detail = await api(`/api/candidates/${c.id}`);
    scoresCache[c.id] = detail.scores;
  }));

  matching
    .sort((a, b) => (scoresCache[b.id][b.final_role]?.total_points || 0) - (scoresCache[a.id][a.final_role]?.total_points || 0))
    .forEach((c) => {
      root.appendChild(candidateCard(c, rubrics, scoresCache, () => renderBandTab(tabName, band)));
    });
}

async function getRubrics() {
  if (!RUBRICS) RUBRICS = await api("/api/rubrics");
  return RUBRICS;
}

// ---------- Auto-Reject Log ----------

async function renderAutoRejectLog() {
  const root = document.getElementById("tab-autoreject");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Auto-reject log"));

  const candidates = await api("/api/candidates");
  const rejected = candidates.filter((c) => c.final_band === "AUTO_REJECT");

  const processBtn = el("button", {
    onclick: async () => {
      processBtn.disabled = true;
      try {
        const data = await api("/api/send-queue/process", { method: "POST" });
        if (data.results.length) {
          toast(`Processed ${data.results.length} candidate(s).`, "success");
        } else {
          toast("Nothing due yet.", "info");
        }
        renderAutoRejectLog();
      } finally {
        processBtn.disabled = false;
      }
    },
  }, "Process send queue");
  root.appendChild(processBtn);

  if (!rejected.length) {
    root.appendChild(el("div", { class: "banner info" }, "No auto-rejected candidates yet."));
    return;
  }

  const scoresCache = {};
  await Promise.all(rejected.map(async (c) => {
    const detail = await api(`/api/candidates/${c.id}`);
    scoresCache[c.id] = detail.scores;
  }));

  rejected.forEach((c) => {
    const score = scoresCache[c.id][c.final_role] || {};
    const alreadySent = !!c.resend_message_id;
    const row = el("div", { class: "log-row" }, [
      el("span", {}, c.name || c.id),
      el("span", {}, c.applied_role),
      el("span", {}, String(score.total_points ?? "-")),
      el("span", {}, (c.reason_codes || []).join(", ") || "-"),
      el("span", {}, alreadySent ? "Sent" : (c.auto_reject_send_after || "-")),
      el("button", {
        disabled: alreadySent ? "true" : undefined,
        onclick: async () => {
          await api(`/api/candidates/${c.id}/override`, { method: "POST" });
          toast("Moved to Review.", "success");
          renderAutoRejectLog();
        },
      }, "Override -> Review"),
    ]);
    root.appendChild(row);

    const draftCard = el("div", { class: "card" });
    const draftHeader = el("div", { class: "card-header", onclick: () => draftCard.classList.toggle("open") },
      [el("span", {}, `Rejection email draft -- ${c.name || c.id}`), el("span", {}, "⌄")]);
    const draftBody = el("div", { class: "card-body" }, [
      el("div", { class: "muted" }, "Sends automatically after the 48h hold via the send queue -- use Override to stop it."),
      emailDraftBlock(c, { allowSend: false }),
    ]);
    draftCard.appendChild(draftHeader);
    draftCard.appendChild(draftBody);
    root.appendChild(draftCard);
  });
}

// ---------- Decision Log ----------

async function renderDecisionLog() {
  const root = document.getElementById("tab-decisionlog");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Decision log"));

  const events = await api("/api/decision-log");
  if (!events.length) {
    root.appendChild(el("div", { class: "banner info" }, "No events yet."));
    return;
  }

  root.appendChild(el("div", { class: "log-row header" }, ["Timestamp", "Candidate", "Event", "Detail", "Rubric version"].map((h) => el("span", {}, h))));
  events.forEach((e) => {
    root.appendChild(el("div", { class: "log-row" }, [
      el("span", {}, e.created_at), el("span", {}, e.candidate_name),
      el("span", {}, e.event), el("span", {}, e.detail || ""), el("span", {}, e.rubric_version || ""),
    ]));
  });
}

// ---------- All Candidates (debug) ----------

async function renderAllCandidates() {
  const root = document.getElementById("tab-allcandidates");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Candidates"));

  const roleSelect = el("select", {}, [
    el("option", { value: "All" }, "All"), el("option", { value: "PM" }, "PM"), el("option", { value: "SPM" }, "SPM"),
  ]);
  const listDiv = el("div", {});
  roleSelect.addEventListener("change", () => loadList());
  root.appendChild(el("div", { class: "field" }, [el("label", {}, "Filter by role"), roleSelect]));
  root.appendChild(listDiv);

  async function loadList() {
    listDiv.innerHTML = "";
    const candidates = await api(`/api/candidates?role=${roleSelect.value}`);
    if (!candidates.length) {
      listDiv.appendChild(el("div", { class: "banner info" }, "No candidates uploaded yet."));
      return;
    }
    candidates.forEach((c) => {
      const card = el("div", { class: "card" });
      const header = el("div", { class: "card-header", onclick: () => card.classList.toggle("open") }, [
        el("span", {}, `${c.id} -- ${c.name || "(name not detected)"} -- ${c.applied_role} -- ${c.parse_status}`),
        el("span", {}, "⌄"),
      ]);
      const body = el("div", { class: "card-body" }, [
        el("h4", {}, "Extracted fields"),
        el("pre", {}, JSON.stringify({
          email: c.email, phone: c.phone, linkedin: c.linkedin, city: c.city,
          location_flag: c.location_flag, source_file: c.source_file, is_duplicate_of: c.is_duplicate_of,
        }, null, 2)),
        el("h4", {}, "Redacted text sent to the LLM"),
        el("textarea", { rows: "12", readonly: "true" }, c.redacted_text || ""),
      ]);
      card.appendChild(header);
      card.appendChild(body);
      listDiv.appendChild(card);
    });
  }
  loadList();
}

// ---------- Init ----------

setupTabs();
renderUpload();
api("/api/send-queue/process", { method: "POST" }).catch(() => {}); // check-on-load, per spec
