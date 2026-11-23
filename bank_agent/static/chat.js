const $ = (selector) => document.querySelector(selector);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
let sessionId = crypto.randomUUID(),
  busy = false,
  latestReport = null,
  modelMode = false;
const wait = (ms) =>
  new Promise((resolve) => setTimeout(resolve, reducedMotion ? 0 : ms));
const money = (value) =>
  value == null
    ? "N/A"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: 0 });
function cents(value) {
  const [whole, fraction = ""] = String(value).split(".");
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
}
function difference(a, b) {
  const delta = cents(a) - cents(b),
    absolute = delta < 0n ? -delta : delta;
  return (
    (delta < 0n ? "−" : "+") + ((absolute + 50n) / 100n).toLocaleString("en-US")
  );
}
function total(rows, key) {
  return rows.reduce((sum, row) => sum + cents(row[key]), 0n);
}
function decimal(value) {
  return (
    (value / 100n).toString() + "." + (value % 100n).toString().padStart(2, "0")
  );
}
function node(tag, text, cls) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (cls) item.className = cls;
  return item;
}
function analysis(text) {
  const p = node("p", undefined, "analysis");
  p.append(node("strong", "Analysis: "), document.createTextNode(text));
  return p;
}
function section(title, id) {
  const item = node("section", undefined, "report-section");
  item.dataset.section = id;
  item.append(node("h3", title));
  return item;
}
function list(lines) {
  const ul = node("ul");
  lines.forEach((line) => ul.append(node("li", line)));
  return ul;
}
function table(headers, rows, totals) {
  const wrapper = node("div", undefined, "table-wrap"),
    table = node("table"),
    head = node("thead"),
    body = node("tbody");
  const header = node("tr");
  headers.forEach((value) => {
    const cell = node("th", value);
    cell.scope = "col";
    header.append(cell);
  });
  head.append(header);
  rows.forEach((row) => {
    const tr = node("tr");
    row.forEach((value) => tr.append(node("td", value)));
    body.append(tr);
  });
  table.append(head, body);
  if (totals) {
    const foot = node("tfoot"),
      tr = node("tr");
    totals.forEach((value) => tr.append(node("td", value)));
    foot.append(tr);
    table.append(foot);
  }
  wrapper.append(table);
  return wrapper;
}
function comparisonTable(data, key) {
  const previous = data.comparison;
  if (!previous)
    return table(
      ["Bank Group", data.period + " (USD)"],
      data.banks.map((b) => [b.bank, money(b[key])]),
      ["Total", money(data.summary[key])],
    );
  const rows = data.banks.map((b) => {
    const prior = previous.banks.find((p) => p.id === b.id);
    return [
      b.bank,
      money(prior[key]),
      money(b[key]),
      difference(b[key], prior[key]),
    ];
  });
  return table(
    [
      "Bank Group",
      previous.period + " (USD)",
      data.period + " (USD)",
      "Change (USD)",
    ],
    rows,
    [
      "Total",
      money(previous.summary[key]),
      money(data.summary[key]),
      difference(data.summary[key], previous.summary[key]),
    ],
  );
}
function followups(data) {
  const block = section("Follow-up Options", "followups"),
    ul = node("ul", undefined, "followups");
  const bank =
    data.scope && data.scope !== "all" ? data.banks?.[0]?.bank : "Harbor Bank";
  const period = data.period || "2026Q3";
  const questions = [
    [
      "Take a closer look at " + bank + ".",
      "Show the relationship report for " + bank + " in " + period,
    ],
    [
      "Review its bank fees and payment activity.",
      "Analyze fees for " + bank + " in " + period,
    ],
    [
      "Compare fees among all bank groups.",
      "Compare bank fees among all bank groups for " + period,
    ],
    [
      "Review available credit and utilization.",
      "Show credit utilization for " + bank + " in " + period,
    ],
  ];
  questions.forEach(([label, prompt]) => {
    const li = node("li"),
      button = node("button", label);
    button.dataset.prompt = prompt;
    button.disabled = busy;
    li.append(button);
    ul.append(li);
  });
  block.append(ul);
  return block;
}
function relationshipReport(data) {
  const card = node("div", undefined, "report-card");
  card.dataset.kind = data.kind;
  card.dataset.scope = data.scope;
  const scope = data.scope === "all" ? "All Banks" : data.banks[0].bank;
  card.append(
    node("h2", "Bank Relationship Report — " + scope),
    node(
      "p",
      "Reporting period: " +
        data.period +
        "  |  USD, rounded to whole dollars  |  Generated demonstration data",
      "report-meta",
    ),
  );
  const executive = section("0. Executive Summary", "summary");
  executive.append(
    list([
      money(data.summary.accounts) +
        " accounts across " +
        data.banks.length +
        " bank group" +
        (data.banks.length > 1 ? "s" : "") +
        " in the selected scope.",
      "Average cash balance: $" +
        money(data.summary.average_balance) +
        "; outgoing payments: $" +
        money(data.summary.payments) +
        ".",
      "Quarterly bank fees: $" +
        money(data.summary.fees) +
        "; quarter-end credit utilization: " +
        data.summary.utilization +
        "%.",
    ]),
  );
  card.append(executive);
  const accounts = section("1. Bank Accounts", "accounts");
  accounts.append(
    table(
      ["Bank Group", "Account Count"],
      data.banks.map((b) => [b.bank, String(b.accounts)]),
      ["Total", String(data.summary.accounts)],
    ),
    analysis(
      "Account counts include active and dormant accounts. All identifiers and bank labels in this demonstration are fictional.",
    ),
  );
  card.append(accounts);
  const balances = section("2. Bank Account Balances", "balances");
  balances.append(
    comparisonTable(data, "average_balance"),
    node(
      "p",
      "Calendar-day average balances. Comparisons are quarter-over-quarter, not year-over-year.",
      "table-note",
    ),
    analysis(
      data.summary.balance_change_pct === null
        ? "This is the first available quarter; no prior-period comparison is available."
        : "Average cash changed " +
            data.summary.balance_change_pct +
            "% from " +
            data.comparison.period +
            ". " +
            data.insights[0],
    ),
  );
  card.append(balances);
  const payments = section("3. Payment Activity", "payments");
  payments.append(
    comparisonTable(data, "payments"),
    analysis(
      money(data.summary.payment_count) +
        " outgoing transactions are included for " +
        data.period +
        ". These are gross outflows; incoming payments are not netted against them.",
    ),
  );
  card.append(payments);
  const fees = section("4. Bank Fees", "fees");
  fees.append(
    comparisonTable(data, "fees"),
    analysis(
      "Fees cover service and transaction charges within the quarter. Compare transaction mix and contractual terms before interpreting differences as bank pricing.",
    ),
  );
  card.append(fees);
  const credit = section(
    "5. Credit Lines (Snapshot " + data.end + ")",
    "credit",
  );
  const free = (row) =>
    money(decimal(cents(row.credit_limit) - cents(row.credit_used)));
  credit.append(
    table(
      [
        "Bank Group",
        "Total Limit (USD)",
        "Utilized (USD)",
        "Free (USD)",
        "Utilization %",
      ],
      data.banks.map((b) => [
        b.bank,
        money(b.credit_limit),
        money(b.credit_used),
        free(b),
        b.utilization + "%",
      ]),
      [
        "Total",
        money(data.summary.credit_limit),
        money(data.summary.credit_used),
        free(data.summary),
        data.summary.utilization + "%",
      ],
    ),
    analysis(
      "Credit figures are a quarter-end snapshot. The aggregate utilization rate uses total utilized credit divided by the total limit.",
    ),
  );
  card.append(credit);
  const positions = section("6. Debt & Investments", "positions");
  positions.append(
    table(
      ["Bank Group", "Debt (USD)", "Investment (USD)"],
      data.banks.map((b) => [b.bank, money(b.debt), money(b.investment)]),
      ["Total", money(data.summary.debt), money(data.summary.investment)],
    ),
    node(
      "p",
      "Snapshot at " +
        data.end +
        ". Debt and investment positions are presented separately.",
      "table-note",
    ),
  );
  card.append(positions);
  const findings = section("7. Relationship Observations", "findings");
  findings.append(
    list(data.insights),
    node(
      "p",
      "These are descriptive findings from the generated dataset. They do not establish the cause of fee differences or constitute a recommendation to move funds.",
      "table-note",
    ),
  );
  card.append(findings, followups(data));
  return card;
}
function metricReport(data) {
  const card = node("div", undefined, "report-card");
  card.dataset.kind = data.kind;
  card.dataset.scope = data.scope || "all";
  const titles = {
    fees: "Bank Fee Analysis",
    credit: "Credit Line Analysis",
    payments: "Payment Activity",
    positions: "Debt & Investments",
    comparison: "Bank Relationship Comparison",
    accounts: "Bank Account Registry",
  };
  card.append(
    node("h2", titles[data.kind] || "Analysis Results"),
    node(
      "p",
      (data.period || "Account registry") +
        "  |  " +
        (data.currency || "USD") +
        "  |  Generated demonstration data",
      "report-meta",
    ),
  );
  if (data.kind === "accounts") {
    card.append(
      table(
        ["Account", "Bank Group", "Country", "Status"],
        data.accounts.map((a) => [a.id, a.bank, a.country, a.status]),
      ),
      node(
        "p",
        String(data.count) +
          " accounts match the requested filters. DEMO labels are not real account numbers.",
        "table-note",
      ),
    );
    return card;
  }
  const rows =
    data.kind === "fees"
      ? [...data.banks].sort((a, b) => Number(b.fees) - Number(a.fees))
      : data.banks;
  if (data.kind === "fees") {
    const block = section(
      rows.length === 1
        ? "1. Fees for " + rows[0].bank
        : "1. Fees Across Bank Groups",
      "fee-comparison",
    );
    block.append(
      table(
        [
          "Bank Group",
          "Bank Fees (USD)",
          "Outflows (USD)",
          "Fee / Outflow (bps)",
        ],
        rows.map((b) => [b.bank, money(b.fees), money(b.payments), b.fee_bps]),
        [
          "Total",
          money(decimal(total(rows, "fees"))),
          money(decimal(total(rows, "payments"))),
          "—",
        ],
      ),
      node(
        "p",
        "Basis points = fees ÷ outgoing payments × 10,000. This ratio is an analytical measure, not a contracted rate.",
        "table-note",
      ),
    );
    card.append(block);
    const analysisBlock = section("2. How to Read These Costs", "fee-analysis");
    analysisBlock.append(
      list([
        "Compare absolute fees alongside outgoing payment volume; a larger fee total alone does not demonstrate worse pricing.",
        "Review the service mix and account arrangements before attributing costs to a particular cause.",
        "This dataset has no contract pricing or detailed fee-code breakdown, so those explanations cannot be confirmed.",
      ]),
    );
    card.append(analysisBlock);
  } else {
    const definitions = {
      credit: [
        ["bank", "Bank Group"],
        ["credit_limit", "Limit (USD)"],
        ["credit_used", "Utilized (USD)"],
        ["utilization", "Utilization %"],
      ],
      payments: [
        ["bank", "Bank Group"],
        ["payments", "Outflows (USD)"],
        ["payment_count", "Transactions"],
      ],
      positions: [
        ["bank", "Bank Group"],
        ["debt", "Debt (USD)"],
        ["investment", "Investment (USD)"],
      ],
      comparison: [
        ["bank", "Bank Group"],
        ["average_balance", "Avg. Balance (USD)"],
        ["fees", "Fees (USD)"],
        ["utilization", "Credit Used %"],
      ],
    };
    const columns = definitions[data.kind];
    card.append(
      table(
        columns.map(([, title]) => title),
        rows.map((b) =>
          columns.map(([key]) =>
            key === "bank"
              ? b[key]
              : key === "utilization"
                ? b[key] + "%"
                : money(b[key]),
          ),
        ),
      ),
    );
    if (data.evidence)
      card.append(
        node(
          "p",
          data.evidence.credit_and_positions || data.evidence.source,
          "table-note",
        ),
      );
  }
  card.append(followups(data));
  return card;
}
function positionAt(item) {
  const scroller = $("#conversation");
  scroller.scrollTop +=
    item.getBoundingClientRect().top -
    scroller.getBoundingClientRect().top -
    18;
}
function updateJump() {
  const c = $("#conversation");
  $("#jump-latest").hidden =
    document.body.dataset.state === "welcome" ||
    c.scrollHeight - c.clientHeight - c.scrollTop < 160;
}
function toggleLibrary(open) {
  $("#prompt-library").hidden = !open;
  $("#library-toggle").setAttribute("aria-expanded", String(open));
}
function controls() {
  $("#send").disabled = busy || !$("#prompt").value.trim();
  $("#new-chat").disabled = busy;
  document
    .querySelectorAll("[data-prompt]")
    .forEach((b) => (b.disabled = busy));
}
async function reveal(card, destination) {
  const children = [...card.children];
  children.forEach((item) => (item.hidden = true));
  destination.append(card);
  for (const child of children) {
    child.hidden = false;
    await wait(child.classList.contains("report-section") ? 85 : 30);
  }
}
async function send(text) {
  const message = text.trim();
  if (!message || busy) return;
  busy = true;
  toggleLibrary(false);
  $("#options").hidden = true;
  $("#more").setAttribute("aria-expanded", "false");
  document.body.dataset.state = "chat";
  $("#prompt").placeholder = "Message Cash and Treasury Assistant…";
  $("#prompt").value = "";
  controls();
  if (!$("#messages").children.length)
    $("#conversation-title").textContent = /report|relationship/i.test(message)
      ? "Full Bank Relationship Report Request"
      : "Bank Relationship Analysis";
  const turn = node("article", undefined, "turn");
  turn.dataset.complete = "false";
  const user = node("div", message, "user-message"),
    reply = node("div", undefined, "assistant-reply");
  const progress = node("div", undefined, "progress-card"),
    track = node("div", undefined, "progress-track"),
    label = node("div", undefined, "progress-label"),
    status = node("span", "Analyzing your request…");
  track.append(node("i"));
  label.append(node("span", undefined, "spinner"), status);
  progress.append(track, label);
  reply.append(progress);
  turn.append(user, reply);
  $("#messages").append(turn);
  positionAt(user);
  $("#chat-status").textContent = "Analyzing your request";
  const details = node("details", undefined, "tool-trace");
  details.append(node("summary", "View analysis details"));
  const traces = [];
  let done = false,
    failed = false,
    hasReport = false;
  async function handle(event) {
    if (event.type === "plan") traces.push(event.text);
    if (event.type === "tool_start") {
      traces.push(event.tool + " " + JSON.stringify(event.arguments));
      status.textContent = "Retrieving the relevant records…";
    }
    if (event.type === "tool_result") {
      traces.push(event.tool + " completed in " + event.duration_ms + " ms");
      status.textContent = "Preparing your report…";
      progress.dataset.done = "true";
      await wait(220);
      progress.hidden = true;
      const data = event.data;
      hasReport = data.kind === "relationship_report";
      await reveal(
        hasReport ? relationshipReport(data) : metricReport(data),
        reply,
      );
      if (hasReport) {
        latestReport = data;
        $("#export").disabled = false;
      }
    }
    if (event.type === "answer") {
      progress.hidden = true;
      if (!hasReport || modelMode)
        reply.append(node("p", event.text, "narrative"));
    }
    if (event.type === "error") {
      failed = true;
      progress.hidden = true;
      reply.append(node("div", event.text, "chat-error"));
    }
    if (event.type === "done") done = true;
  }
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    if (!response.ok)
      throw Error("The request could not be submitted. Please try again.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const item = await reader.read();
      if (item.done) break;
      buffer += decoder.decode(item.value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        if (frame.startsWith("data: "))
          await handle(JSON.parse(frame.slice(6)));
      }
    }
    if (!done)
      throw Error("The response was interrupted. Please retry your question.");
  } catch (error) {
    failed = true;
    progress.hidden = true;
    reply.append(node("div", error.message, "chat-error"));
  } finally {
    progress.hidden = true;
    if (traces.length) {
      details.append(node("pre", traces.join("\n")));
      reply.append(details);
    }
    turn.dataset.complete = "true";
    turn.dataset.success = String(!failed);
    busy = false;
    controls();
    updateJump();
    $("#chat-status").textContent = failed
      ? "Analysis could not finish"
      : "Analysis complete";
  }
}
$("#chat").addEventListener("submit", (event) => {
  event.preventDefault();
  send($("#prompt").value);
});
$("#prompt").addEventListener("input", controls);
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send($("#prompt").value);
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (button) send(button.dataset.prompt);
});
$("#new-chat").addEventListener("click", () => {
  if (busy) return;
  sessionId = crypto.randomUUID();
  latestReport = null;
  $("#messages").replaceChildren();
  document.body.dataset.state = "welcome";
  $("#conversation-title").textContent = "BankScope";
  $("#prompt").value = "";
  $("#prompt").placeholder = "Message BankScope…";
  $("#export").disabled = true;
  toggleLibrary(false);
  updateJump();
  controls();
  $("#prompt").focus();
});
$("#library-toggle").addEventListener("click", () =>
  toggleLibrary($("#prompt-library").hidden),
);
$("#view-library").addEventListener("click", () =>
  toggleLibrary($("#prompt-library").hidden),
);
$("#close-library").addEventListener("click", () => toggleLibrary(false));
$("#more").addEventListener("click", () => {
  const open = $("#options").hidden;
  $("#options").hidden = !open;
  $("#more").setAttribute("aria-expanded", String(open));
});
$("#about").addEventListener("click", () => {
  $("#options").hidden = true;
  $("#more").setAttribute("aria-expanded", "false");
  $("#about-dialog").showModal();
});
$("#close-about").addEventListener("click", () => $("#about-dialog").close());
$("#export").addEventListener("click", () => {
  if (latestReport)
    location.href =
      "/api/export.csv?period=" +
      encodeURIComponent(latestReport.period) +
      "&bank=" +
      encodeURIComponent(latestReport.scope);
  $("#options").hidden = true;
  $("#more").setAttribute("aria-expanded", "false");
});
$("#jump-latest").addEventListener("click", () =>
  $("#conversation").scrollTo({
    top: $("#conversation").scrollHeight,
    behavior: reducedMotion ? "instant" : "smooth",
  }),
);
$("#conversation").addEventListener("scroll", updateJump, { passive: true });
fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw Error();
    return response.json();
  })
  .then((health) => {
    if (health.mode === "llm") {
      modelMode = true;
      $("#mode-note").textContent =
        "BankScope · Synthetic data · Your configured model.";
      $("#model-description").textContent =
        "Model mode uses your configured provider with read-only tools and generated data.";
    }
  })
  .catch(() => {
    $("#mode-note").textContent = "Local service unavailable.";
  });
controls();
