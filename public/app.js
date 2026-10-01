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
  root.appendChild(el("h2", {}, "Upload CVs"));
  root.appendChild(el("p", { class: "muted" },
    "Drop in one or more resumes. If you don't know which role someone is applying for, leave " +
    "it on Auto-detect -- the system scores against both PM and SPM and picks the best fit from " +
    "their experience; you can always override per file below."));

  const roleSelect = el("select", {}, [
    el("option", { value: "AUTO" }, "Auto-detect (recommended)"),
    el("option", { value: "PM" }, "Product Manager"),
    el("option", { value: "SPM" }, "Senior Product Manager"),
  ]);
  root.appendChild(el("div", { class: "field" }, [
    el("label", {}, "Default role for this batch"), roleSelect,
  ]));

  const dropZone = el("div", { class: "dropzone" }, [
    el("div", { class: "dropzone-icon" }, "📄"),
    el("div", {}, "Drag & drop resumes here, or click to browse"),
    el("div", { class: "muted small" }, "PDF or DOCX"),
  ]);
  const fileInput = el("input", { type: "file", multiple: "true", accept: ".pdf,.docx", class: "hidden-input" });
  dropZone.appendChild(fileInput);
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    fileInput.files = e.dataTransfer.files;
    fileInput.dispatchEvent(new Event("change"));
  });
  root.appendChild(el("div", { class: "field" }, [el("label", {}, "Resumes"), dropZone]));

  const fileListDiv = el("div", { class: "file-list" });
  root.appendChild(fileListDiv);

  const overrides = {};
  let selectedFiles = [];
  fileInput.addEventListener("change", () => {
    selectedFiles = Array.from(fileInput.files);
    fileListDiv.innerHTML = "";
    selectedFiles.forEach((f) => {
      const sel = el("select", {}, [
        el("option", { value: "" }, "(use default)"),
        el("option", { value: "PM" }, "PM"),
        el("option", { value: "SPM" }, "SPM"),
      ]);
      sel.addEventListener("change", () => { overrides[f.name] = sel.value; });
      fileListDiv.appendChild(el("div", { class: "file-list-item" }, [
        el("span", { class: "file-name" }, `📎 ${f.name}`), sel,
      ]));
    });
    submitBtn.disabled = selectedFiles.length === 0;
  });

  const progressDiv = el("div", { class: "progress-list" });
  const submitBtn = el("button", {
    class: "primary",
    disabled: "true",
    onclick: async () => {
      if (!selectedFiles.length) return;
      submitBtn.disabled = true;
      progressDiv.innerHTML = "";
      const stepLine = el("div", { class: "spinner" }, "Uploading and reading resumes...");
      progressDiv.appendChild(stepLine);

      const fd = new FormData();
      fd.append("default_role", roleSelect.value);
      const cleanOverrides = {};
      for (const [k, v] of Object.entries(overrides)) {
        if (v) cleanOverrides[k] = v;
      }
      fd.append("role_overrides", JSON.stringify(cleanOverrides));
      selectedFiles.forEach((f) => fd.append("files", f));

      let uploadResults;
      try {
        const data = await api("/api/upload", { method: "POST", body: fd });
        uploadResults = data.results;
      } catch {
        stepLine.remove();
        submitBtn.disabled = false;
        return;
      }

      const scoreable = uploadResults.filter((r) => r.status === "ok" || r.status === "duplicate");
      stepLine.textContent = `Uploaded ${uploadResults.length} file(s). Scoring ${scoreable.length}...`;

      const rows = {};
      uploadResults.forEach((r) => {
        const label = r.status === "duplicate" ? "duplicate -- already on file"
          : r.status === "failed" ? `failed -- ${r.error || "unexpected error"}`
          : "queued";
        const row = el("div", { class: "progress-row" }, [
          el("span", {}, r.filename),
          el("span", { class: "tag" }, label),
        ]);
        if (r.candidate_id) rows[r.candidate_id] = row;
        progressDiv.appendChild(row);
      });

      for (const r of scoreable) {
        if (r.status === "duplicate") continue;
        const row = rows[r.candidate_id];
        row.lastChild.textContent = "scoring...";
        try {
          const result = await api(`/api/candidates/${r.candidate_id}/score`, { method: "POST" });
          if (result.status !== "scored") {
            row.lastChild.textContent = `${result.name || r.filename}: ${result.status}`;
            continue;
          }
          row.lastChild.textContent = `${result.name}: ${result.detail} -- generating brief/email...`;
          // Separate request on purpose: this is its own LLM call, and combining it with
          // scoring in one request risked exceeding Vercel's per-function time limit.
          try {
            await api(`/api/candidates/${r.candidate_id}/followup`, { method: "POST" });
            row.lastChild.textContent = `${result.name}: ${result.detail}`;
          } catch {
            row.lastChild.textContent = `${result.name}: ${result.detail} -- brief/email generation failed, retry from the Needs Attention tab`;
          }
        } catch {
          row.lastChild.textContent = "scoring failed -- retry from the Needs Attention tab";
        }
      }

      stepLine.textContent = "Done. Check Shortlist, Review, or Auto-Reject Log for results.";
      toast("Upload and scoring complete.", "success");
      fileInput.value = "";
      fileListDiv.innerHTML = "";
      selectedFiles = [];
      submitBtn.disabled = true;
    },
  }, "Upload & score");
  root.appendChild(submitBtn);
  root.appendChild(progressDiv);
}

// ---------- Score ----------

async function renderScore() {
  const root = document.getElementById("tab-score");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Needs attention"));
  root.appendChild(el("p", { class: "muted" },
    "Scoring runs automatically right after upload. This tab is only for stragglers -- a candidate " +
    "whose scoring call failed or timed out, or was uploaded some other way."));

  const candidates = await api("/api/candidates");
  // Duplicates and failed-to-parse files are never eligible for scoring by design (see
  // db.list_candidates_needing_scoring) -- only a genuinely-parsed, still-unscored
  // candidate is an actual straggler worth a retry button.
  const pending = candidates.filter((c) => c.score_status === "not_scored" && c.parse_status === "ok");
  const duplicates = candidates.filter((c) => c.score_status === "not_scored" && c.parse_status === "duplicate");
  const needsReview = candidates.filter((c) => c.score_status === "needs_manual_review");
  // Scored successfully, but the follow-up brief/email-draft call never completed --
  // e.g. it was killed mid-flight by a function timeout.
  const missingFollowup = candidates.filter((c) => {
    if (c.score_status !== "scored") return false;
    if (c.final_band === "AUTO_REJECT") return !c.email_body;
    if (c.final_band === "SHORTLIST" || c.final_band === "REVIEW") return !c.interview_brief_why;
    return false;
  });

  if (!pending.length && !needsReview.length && !missingFollowup.length) {
    root.appendChild(el("div", { class: "banner success" }, "Nothing waiting -- everything uploaded so far has been scored."));
    if (duplicates.length) {
      root.appendChild(el("p", { class: "muted" },
        `(${duplicates.length} duplicate upload(s) on file, correctly skipped -- they're already scored under their first upload.)`));
    }
    return;
  }

  if (pending.length) {
    root.appendChild(el("p", {}, `${pending.length} candidate(s) never got scored.`));
  }
  if (duplicates.length) {
    root.appendChild(el("p", { class: "muted" },
      `${duplicates.length} duplicate upload(s) skipped, not shown here -- see the original candidate instead.`));
  }

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
  }, "Retry scoring");
  if (pending.length) root.appendChild(btn);
  root.appendChild(resultsDiv);

  if (missingFollowup.length) {
    root.appendChild(el("h3", {}, "Scored, but brief/email draft never finished"));
    missingFollowup.forEach((c) => {
      const label = c.final_band === "AUTO_REJECT" ? "rejection email" : "interview brief";
      const status = el("span", { class: "tag" }, `Generate ${label}`);
      const row = el("div", { class: "progress-row" }, [
        el("span", {}, `${c.name || c.id} (${c.final_band})`),
        status,
      ]);
      const retryBtn = el("button", {
        onclick: async () => {
          retryBtn.disabled = true;
          status.textContent = "generating...";
          try {
            await api(`/api/candidates/${c.id}/followup`, { method: "POST" });
            status.textContent = "done";
            renderScore();
          } catch {
            status.textContent = "failed again -- try once more";
            retryBtn.disabled = false;
          }
        },
      }, "Retry");
      row.appendChild(retryBtn);
      root.appendChild(row);
    });
  }

  if (needsReview.length) {
    root.appendChild(el("h3", {}, "Failed validation twice"));
    needsReview.forEach((c) => root.appendChild(el("div", { class: "banner warn" }, `${c.name || c.id} (${c.applied_role})`)));
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

function renderSummaryBar(container, candidates, roleKey, roleLabel, rubrics) {
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

  const reasonText = s.most_common_reason_code === "-" ? "-" : reasonCodeText(rubrics, s.most_common_reason_code);
  const flagDef = rubrics.red_flags.flags.find((f) => f.id === s.most_common_red_flag);
  const flagText = s.most_common_red_flag === "-" ? "-" : (flagDef ? `${s.most_common_red_flag} (${flagDef.name})` : s.most_common_red_flag);
  container.appendChild(el("div", { class: "summary-caption" },
    `Most common reason code: ${reasonText} · Most common red flag: ${flagText}`));
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

  const bandClass = candidate.final_band.toLowerCase();
  let subtitle = `${scoredRole.toUpperCase()} · ${score.total_points} pts`;
  if (candidate.final_band_flag) subtitle += ` · ${candidate.final_band_flag}`;
  if (candidate.reroute_label) subtitle += ` · ${candidate.reroute_label}`;

  const card = el("div", { class: `card band-${bandClass}` });
  const header = el("div", { class: "card-header", onclick: () => card.classList.toggle("open") }, [
    el("span", {}, [
      el("span", {}, candidate.name || candidate.id),
      el("span", { class: `badge ${bandClass}` }, candidate.final_band.replace("_", " ")),
      el("span", { class: "tag" }, ` · ${subtitle}`),
    ]),
    el("span", { class: "chevron" }, "⌄"),
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

  renderSummaryBar(root, candidates, "pm", "PM", rubrics);
  renderSummaryBar(root, candidates, "spm", "SPM", rubrics);
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

  const byScoreDesc = (a, b) => (scoresCache[b.id][b.final_role]?.total_points || 0) - (scoresCache[a.id][a.final_role]?.total_points || 0);

  // Kept as two clearly separate sections rather than one mixed list -- PM and SPM are
  // different rubrics with different thresholds, so "Shortlist" means a different bar
  // for each, and mixing them made it hard to see who's shortlisted for which role.
  [["pm", "PM"], ["spm", "SPM"]].forEach(([roleKey, roleLabel]) => {
    const group = matching.filter((c) => c.final_role === roleKey).sort(byScoreDesc);
    root.appendChild(el("h3", {}, `${roleLabel} -- ${band[0] + band.slice(1).toLowerCase()} (${group.length})`));
    if (!group.length) {
      root.appendChild(el("p", { class: "muted" }, `No ${roleLabel} candidates in ${band} yet.`));
      return;
    }
    group.forEach((c) => {
      root.appendChild(candidateCard(c, rubrics, scoresCache, () => renderBandTab(tabName, band)));
    });
  });
}

async function getRubrics() {
  if (!RUBRICS) RUBRICS = await api("/api/rubrics");
  return RUBRICS;
}

// ---------- Auto-Reject Log ----------

function reasonCodeText(rubrics, code) {
  const desc = rubrics.reason_codes && rubrics.reason_codes[code];
  return desc ? `${code} (${desc})` : code;
}

function reasonCodesLine(rubrics, codes) {
  if (!codes || !codes.length) return "-";
  return codes.map((c) => reasonCodeText(rubrics, c)).join("; ");
}

async function renderAutoRejectLog() {
  const root = document.getElementById("tab-autoreject");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Auto-reject log"));
  root.appendChild(el("p", { class: "muted" },
    "Each of these holds for 48 hours before its rejection email sends automatically. " +
    "Override any of them into Review before then if you want a second look."));

  const [rubrics, candidates] = await Promise.all([getRubrics(), api("/api/candidates")]);
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

  root.appendChild(el("div", { class: "log-row header" }, [
    "Candidate", "Applied as", "Score", "Reason codes", "Sends", "",
  ].map((h) => el("span", {}, h))));

  rejected.forEach((c) => {
    const score = scoresCache[c.id][c.final_role] || {};
    const alreadySent = !!c.resend_message_id;
    const sendsText = alreadySent ? "Sent ✓" : (c.auto_reject_send_after ? formatDueIn(c.auto_reject_send_after) : "-");
    const row = el("div", { class: "log-row" }, [
      el("span", {}, c.name || c.id),
      el("span", { class: "tag" }, c.applied_role),
      el("span", {}, String(score.total_points ?? "-")),
      el("span", { class: "tag" }, reasonCodesLine(rubrics, c.reason_codes)),
      el("span", { class: alreadySent ? "" : "tag" }, sendsText),
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

    const scoreCard = el("div", { class: "card" });
    const scoreHeader = el("div", { class: "card-header", onclick: () => scoreCard.classList.toggle("open") },
      [el("span", {}, `Why ${c.name || c.id} was rejected -- full score breakdown`), el("span", {}, "⌄")]);
    const scoreBody = el("div", { class: "card-body" });
    if (c.location_flag_note) {
      scoreBody.appendChild(el("div", { class: "banner info" }, `Location: ${c.location_flag_note}`));
    }
    if (c.better_fit_note) {
      scoreBody.appendChild(el("div", { class: "banner warn" }, `Best fit check: ${c.better_fit_note}`));
    }
    scoreBody.appendChild(el("h4", {}, "Gates"));
    scoreBody.appendChild(gatesLine(score.gates, c.years_pm_experience));
    scoreBody.appendChild(el("h4", {}, "Criteria"));
    scoreBody.appendChild(criteriaTable(score.criteria));
    scoreBody.appendChild(el("h4", {}, "Red flags"));
    scoreBody.appendChild(redFlagsBlock(c.red_flags || [], rubrics));
    scoreBody.appendChild(el("h4", {}, "Band reasoning"));
    scoreBody.appendChild(el("div", {}, bandReasoning(c.final_role, score, rubrics)));
    scoreCard.appendChild(scoreHeader);
    scoreCard.appendChild(scoreBody);
    root.appendChild(scoreCard);

    const draftCard = el("div", { class: "card" });
    const draftHeader = el("div", { class: "card-header", onclick: () => draftCard.classList.toggle("open") },
      [el("span", {}, `Rejection email draft -- ${c.name || c.id}`), el("span", {}, "⌄")]);
    const draftBody = el("div", { class: "card-body" }, [
      el("div", { class: "muted" }, "Sends automatically after the 48h hold, or click Send below to send it right now. Use Override instead if you want a second look before it goes out."),
      emailDraftBlock(c, { allowSend: true, onChange: renderAutoRejectLog }),
    ]);
    draftCard.appendChild(draftHeader);
    draftCard.appendChild(draftBody);
    root.appendChild(draftCard);
  });
}

// ---------- Decision Log ----------

const EVENT_LABELS = {
  uploaded: { icon: "📥", text: "Uploaded" },
  scored: { icon: "🧮", text: "Scored" },
  banded: { icon: "🚫", text: "Auto-rejected -- queued" },
  brief_generated: { icon: "📝", text: "Interview brief ready" },
  brief_generation_failed: { icon: "⚠️", text: "Brief generation failed" },
  email_drafted: { icon: "✉️", text: "Email drafted" },
  email_draft_failed: { icon: "⚠️", text: "Email draft failed" },
  advanced: { icon: "✅", text: "Advanced" },
  passed: { icon: "❌", text: "Passed" },
  overridden: { icon: "↩️", text: "Overridden to Review" },
  email_sent: { icon: "📤", text: "Email sent" },
  email_send_failed: { icon: "⚠️", text: "Send failed" },
  needs_manual_review: { icon: "⚠️", text: "Needs manual review" },
};

function formatDueIn(isoString) {
  const diffMs = new Date(isoString).getTime() - Date.now();
  if (diffMs <= 0) return "due now";
  const mins = Math.round(diffMs / 60000);
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

function relativeTime(isoString) {
  const then = new Date(isoString);
  const diffMs = Date.now() - then.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return then.toLocaleDateString();
}

async function renderDecisionLog() {
  const root = document.getElementById("tab-decisionlog");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "Decision log"));
  root.appendChild(el("p", { class: "muted" }, "Newest first -- everything that's happened to every candidate, in order."));

  const events = await api("/api/decision-log");
  if (!events.length) {
    root.appendChild(el("div", { class: "banner info" }, "No events yet."));
    return;
  }

  const names = [...new Set(events.map((e) => e.candidate_name))].sort();
  const filterSelect = el("select", {}, [
    el("option", { value: "" }, "All candidates"),
    ...names.map((n) => el("option", { value: n }, n)),
  ]);
  root.appendChild(el("div", { class: "field" }, [el("label", {}, "Filter by candidate"), filterSelect]));

  const listDiv = el("div", { class: "timeline" });
  root.appendChild(listDiv);

  function draw() {
    listDiv.innerHTML = "";
    const filtered = filterSelect.value ? events.filter((e) => e.candidate_name === filterSelect.value) : events;
    filtered.forEach((e) => {
      const meta = EVENT_LABELS[e.event] || { icon: "•", text: e.event };
      const isWarning = e.event.includes("fail") || e.event === "needs_manual_review";
      listDiv.appendChild(el("div", { class: `timeline-row${isWarning ? " timeline-warn" : ""}` }, [
        el("span", { class: "timeline-icon" }, meta.icon),
        el("span", { class: "timeline-candidate" }, e.candidate_name),
        el("span", { class: "timeline-event" }, meta.text),
        el("span", { class: "timeline-detail" }, e.detail || ""),
        el("span", { class: "timeline-time", title: e.created_at }, relativeTime(e.created_at)),
      ]));
    });
  }
  filterSelect.addEventListener("change", draw);
  draw();
}

// ---------- All Candidates (debug) ----------

const PARSE_STATUS_LABEL = { ok: "Parsed", duplicate: "Duplicate", needs_manual_review: "Parse failed" };
const SCORE_STATUS_LABEL = { not_scored: "Not scored yet", scored: "Scored", needs_manual_review: "Needs review" };

function statusPill(text, kind) {
  return el("span", { class: `badge ${kind}` }, text);
}

function contactField(label, value) {
  if (!value) return null;
  return el("div", { class: "kv-row" }, [el("span", { class: "kv-label" }, label), el("span", {}, value)]);
}

async function renderAllCandidates() {
  const root = document.getElementById("tab-allcandidates");
  root.innerHTML = "";
  root.appendChild(el("h2", {}, "All candidates"));
  root.appendChild(el("p", { class: "muted" }, "Every resume uploaded so far, whatever its current stage. Click a row for details."));

  const roleSelect = el("select", {}, [
    el("option", { value: "All" }, "All roles"), el("option", { value: "PM" }, "PM"), el("option", { value: "SPM" }, "SPM"),
  ]);
  const statusSelect = el("select", {}, [
    el("option", { value: "All" }, "All statuses"),
    el("option", { value: "SHORTLIST" }, "Shortlist"),
    el("option", { value: "REVIEW" }, "Review"),
    el("option", { value: "AUTO_REJECT" }, "Auto-reject"),
    el("option", { value: "NOT_SCORED" }, "Not yet scored"),
  ]);
  const sortSelect = el("select", {}, [
    el("option", { value: "newest" }, "Newest uploaded first"),
    el("option", { value: "oldest" }, "Oldest uploaded first"),
  ]);
  const listDiv = el("div", {});
  roleSelect.addEventListener("change", () => loadList());
  statusSelect.addEventListener("change", () => loadList());
  sortSelect.addEventListener("change", () => loadList());
  const filters = el("div", { style: "display:flex; gap:24px; flex-wrap:wrap;" }, [
    el("div", { class: "field", style: "margin-bottom:0;" }, [el("label", {}, "Filter by applied role"), roleSelect]),
    el("div", { class: "field", style: "margin-bottom:0;" }, [el("label", {}, "Filter by status"), statusSelect]),
    el("div", { class: "field", style: "margin-bottom:0;" }, [el("label", {}, "Sort by upload time"), sortSelect]),
  ]);
  root.appendChild(filters);
  root.appendChild(listDiv);

  function candidateCardRow(c, rubrics, scores) {
    const card = el("div", { class: "card" });
    const parseKind = c.parse_status === "ok" ? "shortlist" : c.parse_status === "duplicate" ? "review" : "auto_reject";
    const scoreKind = c.score_status === "scored" ? "shortlist" : c.score_status === "needs_manual_review" ? "auto_reject" : "review";

    const row = el("div", { class: "candidate-row" }, [
      el("span", { class: "kv-name" }, c.name || "Unnamed candidate"),
      el("span", { class: "tag" }, c.applied_role),
      statusPill(PARSE_STATUS_LABEL[c.parse_status] || c.parse_status, parseKind),
      statusPill(SCORE_STATUS_LABEL[c.score_status] || c.score_status, scoreKind),
      el("span", { class: "tag" }, c.final_band ? c.final_band.replace("_", " ") : "-"),
      el("span", { class: "tag" }, c.created_at ? relativeTime(c.created_at) : "-"),
    ]);
    row.addEventListener("click", () => card.classList.toggle("open"));

    const body = el("div", { class: "card-body" }, [
      el("h4", {}, "Contact"),
      el("div", { class: "kv-list" }, [
        contactField("Email", c.email),
        contactField("Phone", c.phone),
        contactField("LinkedIn", c.linkedin),
        contactField("City", c.city),
        contactField("Location flag", c.location_flag),
        contactField("Source file", c.source_file),
        c.is_duplicate_of ? contactField("Duplicate of", c.is_duplicate_of) : null,
      ].filter(Boolean)),
    ]);

    const score = scores && c.final_role ? scores[c.final_role] : null;
    if (score) {
      body.appendChild(el("h4", {}, "Score details"));
      if (c.location_flag_note) {
        body.appendChild(el("div", { class: "banner info" }, `Location: ${c.location_flag_note}`));
      }
      if (c.better_fit_note) {
        body.appendChild(el("div", { class: "banner warn" }, `Best fit check: ${c.better_fit_note}`));
      }
      body.appendChild(el("div", { class: "muted", style: "margin-bottom:8px;" }, `${c.final_role.toUpperCase()} -- ${score.total_points} pts -- ${c.final_band ? c.final_band.replace("_", " ") : score.band}`));
      body.appendChild(el("h4", {}, "Gates"));
      body.appendChild(gatesLine(score.gates, c.years_pm_experience));
      body.appendChild(el("h4", {}, "Criteria"));
      body.appendChild(criteriaTable(score.criteria));
      body.appendChild(el("h4", {}, "Red flags"));
      body.appendChild(redFlagsBlock(c.red_flags || [], rubrics));
      body.appendChild(el("h4", {}, "Band reasoning"));
      body.appendChild(el("div", {}, bandReasoning(c.final_role, score, rubrics)));
    } else if (c.score_status !== "scored") {
      body.appendChild(el("h4", {}, "Score details"));
      body.appendChild(el("p", { class: "muted" }, "Not scored yet."));
    }

    const toggleBtn = el("button", {
      onclick: (e) => {
        e.stopPropagation();
        const shown = redactedBlock.style.display !== "none";
        redactedBlock.style.display = shown ? "none" : "block";
        toggleBtn.textContent = shown ? "Show redacted text sent to the LLM" : "Hide redacted text";
      },
    }, "Show redacted text sent to the LLM");
    const redactedBlock = el("textarea", { rows: "12", readonly: "true", style: "display:none;margin-top:10px;" }, c.redacted_text || "");
    body.appendChild(toggleBtn);
    body.appendChild(redactedBlock);

    card.appendChild(row);
    card.appendChild(body);
    return card;
  }

  function appendGroup(container, title, group, rubrics, scoresCache) {
    container.appendChild(el("h3", {}, `${title} (${group.length})`));
    if (!group.length) {
      container.appendChild(el("p", { class: "muted" }, `No ${title} candidates yet.`));
      return;
    }
    container.appendChild(el("div", { class: "candidate-row header" }, [
      "Name", "Applied as", "Parse", "Scoring", "Band", "Uploaded",
    ].map((h) => el("span", {}, h))));
    group.forEach((c) => container.appendChild(candidateCardRow(c, rubrics, scoresCache[c.id])));
  }

  // A candidate's role isn't settled until scoring runs (auto-detect resolves it from
  // experience), so grouping is keyed off final_role when present and falls back to an
  // explicit applied_role choice, otherwise the candidate sits in "Not yet scored" rather
  // than being guessed into PM or SPM.
  function effectiveRole(c) {
    if (c.final_role) return c.final_role.toLowerCase();
    if (c.applied_role && c.applied_role !== "AUTO") return c.applied_role.toLowerCase();
    return null;
  }

  function matchesRole(c) {
    const role = roleSelect.value;
    if (role === "All") return true;
    return effectiveRole(c) === role.toLowerCase();
  }

  function matchesStatus(c) {
    const status = statusSelect.value;
    if (status === "All") return true;
    if (status === "NOT_SCORED") return !c.final_band;
    return c.final_band === status;
  }

  // Switching either filter can fire loadList() again before the previous call's fetches
  // finish (especially the per-candidate score fetches below, which are slow on a cold
  // Vercel/Neon connection) -- without this guard, an earlier call's results could land
  // AFTER a newer one's and either show stale data or duplicate rows under the new filter.
  let loadToken = 0;

  async function loadList() {
    const myToken = ++loadToken;
    listDiv.innerHTML = "";
    listDiv.appendChild(el("div", { class: "spinner" }, "Loading candidates..."));

    // The backend's role= query filters on applied_role, which is almost always "AUTO"
    // (the uploader rarely knows PM vs SPM up front) -- the real PM/SPM split only exists
    // in final_role, computed after scoring. So the role filter is applied client-side
    // using the same effectiveRole() logic the PM/SPM grouping below already uses, instead
    // of asking the backend to filter on a field that's usually just "AUTO" for everyone.
    const [rubrics, all] = await Promise.all([getRubrics(), api("/api/candidates?role=All")]);
    const candidates = all.filter((c) => matchesRole(c) && matchesStatus(c));
    candidates.sort((a, b) => {
      const diff = new Date(a.created_at) - new Date(b.created_at);
      return sortSelect.value === "oldest" ? diff : -diff;
    });
    if (myToken !== loadToken) return;

    if (!candidates.length) {
      listDiv.innerHTML = "";
      listDiv.appendChild(el("div", { class: "banner info" }, "No candidates match this filter."));
      return;
    }

    const scoresCache = {};
    await Promise.all(candidates.filter((c) => c.score_status === "scored").map(async (c) => {
      const detail = await api(`/api/candidates/${c.id}`);
      scoresCache[c.id] = detail.scores;
    }));
    if (myToken !== loadToken) return;

    listDiv.innerHTML = "";
    const pm = candidates.filter((c) => effectiveRole(c) === "pm");
    const spm = candidates.filter((c) => effectiveRole(c) === "spm");
    const unassigned = candidates.filter((c) => effectiveRole(c) === null);

    appendGroup(listDiv, "PM", pm, rubrics, scoresCache);
    appendGroup(listDiv, "SPM", spm, rubrics, scoresCache);
    if (unassigned.length) appendGroup(listDiv, "Not yet scored", unassigned, rubrics, scoresCache);
  }
  loadList();
}

// ---------- Init ----------

setupTabs();
renderUpload();
api("/api/send-queue/process", { method: "POST" }).catch(() => {}); // check-on-load, per spec
