const $ = (selector) => document.querySelector(selector);
const usd = (value) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
const compact = (value) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(Number(value));
const sessionId = crypto.randomUUID();
let busy = false;
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function showError(message) {
  $("#error").textContent = message;
  $("#error").hidden = !message;
}
function updateReport(data) {
  $("#period").value = data.period;
  $("#bank").value = data.scope;
  $("#cash").textContent = compact(data.summary.average_balance);
  $("#payments").textContent = compact(data.summary.payments);
  $("#fees").textContent = compact(data.summary.fees);
  $("#credit").textContent = data.summary.utilization + "%";
  const change = data.summary.balance_change_pct;
  $("#cash-change").textContent =
    change === null
      ? "No prior quarter available"
      : (Number(change) >= 0 ? "↗ " : "↘ ") + change + "% vs. prior quarter";
  $("#payment-count").textContent =
    data.summary.payment_count.toLocaleString() + " outgoing transactions";
  $(".period-label").textContent = data.period;
  $("#bank-count").textContent =
    data.banks.length + " BANK GROUP" + (data.banks.length > 1 ? "S" : "");
  $("#account-count").textContent =
    data.summary.accounts + " synthetic accounts";
  $("#bars").replaceChildren();
  $("#bank-table tbody").replaceChildren();
  data.banks.forEach((bank) => {
    const row = element("div", undefined, "bar-row");
    row.append(element("span", bank.bank));
    const track = element("div", undefined, "bar-track"),
      fill = element("div", undefined, "bar-fill");
    fill.style.width = Number(bank.balance_share) + "%";
    track.append(fill);
    row.append(
      track,
      element("b", compact(bank.average_balance)),
      element("small", Number(bank.balance_share).toFixed(1) + "%"),
    );
    $("#bars").append(row);
    const tr = element("tr");
    [
      bank.bank,
      usd(bank.average_balance),
      usd(bank.fees),
      bank.fee_bps + " bps",
    ].forEach((value) => tr.append(element("td", value)));
    const td = element("td");
    td.append(
      element(
        "span",
        bank.utilization + "%",
        "util" + (Number(bank.utilization) >= 75 ? " high" : ""),
      ),
    );
    tr.append(td);
    $("#bank-table tbody").append(tr);
  });
  $("#insights").replaceChildren(
    ...data.insights.map((line) => element("li", line)),
  );
  $("#evidence-items").replaceChildren();
  Object.entries(data.evidence).forEach(([key, value]) =>
    $("#evidence-items").append(
      element("dt", key.replaceAll("_", " ")),
      element("dd", value),
    ),
  );
}
async function loadReport() {
  showError("");
  try {
    const response = await fetch(
      "/api/report?period=" + $("#period").value + "&bank=" + $("#bank").value,
    );
    const data = await response.json();
    if (!response.ok) throw Error(data.detail || "Report unavailable");
    updateReport(data);
  } catch (error) {
    showError(error.message);
  }
}
function resultCard(data) {
  const card = element("div", undefined, "chat-result");
  card.append(
    element(
      "h4",
      data.kind.replaceAll("_", " ") +
        " · " +
        (data.period || "Account registry") +
        (data.currency ? " · " + data.currency : ""),
    ),
  );
  const rows = data.banks || data.accounts || [];
  let columns;
  if (data.kind === "relationship_report" || data.kind === "comparison")
    columns = [
      ["bank", "Bank"],
      ["average_balance", "Avg. cash"],
      ["utilization", "Credit %"],
    ];
  else if (data.kind === "fees")
    columns = [
      ["bank", "Bank"],
      ["fees", "Fees"],
      ["fee_bps", "bps"],
    ];
  else if (data.kind === "credit")
    columns = [
      ["bank", "Bank"],
      ["credit_limit", "Limit"],
      ["utilization", "Used %"],
    ];
  else if (data.kind === "payments")
    columns = [
      ["bank", "Bank"],
      ["payments", "Outflows"],
      ["payment_count", "Count"],
    ];
  else if (data.kind === "positions")
    columns = [
      ["bank", "Bank"],
      ["debt", "Debt"],
      ["investment", "Investment"],
    ];
  else
    columns = [
      ["bank", "Bank"],
      ["country", "Country"],
      ["status", "Status"],
    ];
  const table = element("table"),
    thead = element("thead"),
    tr = element("tr"),
    tbody = element("tbody");
  columns.forEach(([, label]) => tr.append(element("th", label)));
  thead.append(tr);
  rows.slice(0, 8).forEach((row) => {
    const tr = element("tr");
    columns.forEach(([key]) => {
      let value = row[key];
      if (
        [
          "average_balance",
          "fees",
          "payments",
          "debt",
          "investment",
          "credit_limit",
        ].includes(key)
      )
        value = compact(value);
      tr.append(element("td", value));
    });
    tbody.append(tr);
  });
  table.append(thead, tbody);
  card.append(table);
  card.append(
    element(
      "small",
      "Generated records · Read-only query" +
        (rows.length > 8 ? " · Showing 8 of " + rows.length : ""),
    ),
  );
  return card;
}
function scrollChat() {
  const container = $("#messages");
  container.scrollTop = container.scrollHeight;
}
async function send(message) {
  if (busy || !message.trim()) return;
  busy = true;
  $("#send").disabled = true;
  document
    .querySelectorAll("[data-prompt]")
    .forEach((b) => (b.disabled = true));
  $(".welcome")?.remove();
  $("#messages").append(element("div", message, "message user"));
  $("#prompt").value = "";
  scrollChat();
  let currentTrace;
  $("#chat-status").textContent = "Analyzing with MCP tools…";
  function handle(event) {
    if (event.type === "plan")
      $("#messages").append(element("div", event.text, "plan"));
    if (event.type === "tool_start") {
      currentTrace = element("details", undefined, "trace");
      currentTrace.append(
        element("summary", "◌ " + event.tool),
        element("pre", JSON.stringify(event.arguments, null, 2)),
      );
      $("#messages").append(currentTrace);
    }
    if (event.type === "tool_result") {
      if (currentTrace)
        currentTrace.querySelector("summary").textContent =
          "✓ " + event.tool + " · " + event.duration_ms + " ms";
      $("#messages").append(resultCard(event.data));
      if (event.data.kind === "relationship_report") updateReport(event.data);
    }
    if (event.type === "answer") {
      const answer = element("div", undefined, "message answer");
      answer.append(
        element("span", "BANKSCOPE ANALYST", "label"),
        document.createTextNode(event.text),
      );
      $("#messages").append(answer);
    }
    if (event.type === "error")
      $("#messages").append(element("div", event.text, "message chat-error"));
    scrollChat();
  }
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    if (!response.ok) throw Error("The request could not be submitted.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        if (frame.startsWith("data: ")) handle(JSON.parse(frame.slice(6)));
      }
    }
  } catch (error) {
    $("#messages").append(element("div", error.message, "message chat-error"));
  } finally {
    busy = false;
    $("#send").disabled = false;
    document
      .querySelectorAll("[data-prompt]")
      .forEach((b) => (b.disabled = false));
    $("#chat-status").textContent =
      "Analysis complete · Synthetic data · Read-only tools";
    scrollChat();
  }
}
$("#chat").addEventListener("submit", (event) => {
  event.preventDefault();
  send($("#prompt").value);
});
$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send($("#prompt").value);
  }
});
document
  .querySelectorAll("[data-prompt]")
  .forEach((button) =>
    button.addEventListener("click", () => send(button.dataset.prompt)),
  );
$("#period").addEventListener("change", loadReport);
$("#bank").addEventListener("change", loadReport);
$("#export").addEventListener("click", () => {
  location.href =
    "/api/export.csv?period=" +
    $("#period").value +
    "&bank=" +
    $("#bank").value;
});
fetch("/api/health")
  .then((r) => r.json())
  .then((health) => {
    if (health.mode === "llm") {
      $("#mode").textContent = "Your model · Read-only MCP tools";
      $("#chat-status").textContent = "Synthetic data · User-configured model";
    }
  })
  .catch(() => showError("Local service is unavailable."));
loadReport();
