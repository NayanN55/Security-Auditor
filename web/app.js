const graphEl = document.getElementById("graph");
const tooltip = document.getElementById("tooltip");
const changeList = document.getElementById("changeList");
const graphSubtitle = document.getElementById("graphSubtitle");
const statUsers = document.getElementById("statUsers");
const statMismatches = document.getElementById("statMismatches");
const statMissing = document.getElementById("statMissing");
const caseTitle = document.getElementById("caseTitle");
const caseName = document.getElementById("caseName");
const caseDescription = document.getElementById("caseDescription");
const instructionList = document.getElementById("instructionList");
const modePill = document.getElementById("modePill");
const viewButtons = document.querySelectorAll("[data-view]");
const animateBtn = document.getElementById("animateBtn");
const dataRoot = document.body.dataset.dataRoot || "../artifacts";

const state = {
  current: null,
  corrected: null,
  runtime: null,
  view: "current",
};

const DATA_PATHS = {
  current: `${dataRoot}/hierarchy_current.json`,
  corrected: `${dataRoot}/hierarchy_corrected.json`,
  runtime: `${dataRoot}/runtime.json`,
};

function setView(view) {
  state.view = view;
  viewButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  graphSubtitle.textContent =
    view === "current" ? "Current placement" : "Corrected placement";
  render();
}

function updateStats() {
  const counts = state.current?.meta?.counts || {};
  statUsers.textContent = counts.users ?? 0;
  statMismatches.textContent = counts.mismatches ?? 0;
  statMissing.textContent = counts.missing ?? 0;
}

function updateCaseDetails() {
  const selectedCase = state.runtime?.selected_case;
  if (!selectedCase) return;

  if (caseTitle) caseTitle.textContent = selectedCase.title;
  if (caseName) caseName.textContent = selectedCase.name;
  if (caseDescription) caseDescription.textContent = selectedCase.description;
  if (modePill) modePill.textContent = (state.runtime.mode || "live").toUpperCase();

  if (instructionList) {
    instructionList.innerHTML = "";
    selectedCase.instructions.forEach((instruction) => {
      const item = document.createElement("li");
      item.textContent = instruction;
      instructionList.appendChild(item);
    });
  }
}

function updateChangeList() {
  changeList.innerHTML = "";
  const changes = state.current?.meta?.changes || [];
  if (!changes.length) {
    const item = document.createElement("li");
    item.textContent = "No mismatches detected. Everything aligns.";
    changeList.appendChild(item);
    return;
  }

  changes.forEach((change) => {
    const item = document.createElement("li");
    item.innerHTML = `<strong>${change.user}</strong> moves from <em>${change.from}</em> to <em>${change.to}</em>.`;
    changeList.appendChild(item);
  });
}

function nodeRadius(d) {
  if (d.data.type === "root") return 10;
  if (d.data.type === "department") return 8;
  return 6;
}

function nodeClass(d) {
  const status = d.data.status ? ` ${d.data.status}` : "";
  return `node ${d.data.type}${status}`;
}

function showTooltip(event, d) {
  if (d.data.type !== "user") return;
  const permissions = d.data.permissions || [];
  const permissionList = permissions.length
    ? `<ul class="tooltip-list">${permissions
        .map((item) => `<li>${item}</li>`)
        .join("")}</ul>`
    : "<div>No policies attached.</div>";

  tooltip.innerHTML = `
    <div class="tooltip-title">${d.data.name}</div>
    <div>Dept: ${d.data.department}</div>
    <div>Expected: ${d.data.expected_department}</div>
    <div style="margin-top: 6px;">Policies</div>
    ${permissionList}
  `;
  tooltip.classList.add("visible");
  tooltip.setAttribute("aria-hidden", "false");
  moveTooltip(event);
}

function moveTooltip(event) {
  tooltip.style.left = `${event.clientX + 16}px`;
  tooltip.style.top = `${event.clientY + 16}px`;
}

function hideTooltip() {
  tooltip.classList.remove("visible");
  tooltip.setAttribute("aria-hidden", "true");
}

function render() {
  if (!state.current || !state.corrected) return;

  const data = state.view === "current" ? state.current : state.corrected;
  const root = d3.hierarchy(data.tree);
  const dx = 36;
  const dy = 190;
  const treeLayout = d3.tree().nodeSize([dx, dy]);
  treeLayout(root);

  let x0 = Infinity;
  let x1 = -Infinity;
  root.each((d) => {
    if (d.x < x0) x0 = d.x;
    if (d.x > x1) x1 = d.x;
  });

  const margin = { top: 30, right: 100, bottom: 30, left: 100 };
  const width = Math.max(
    graphEl.clientWidth || 800,
    root.height * dy + margin.left + margin.right
  );
  const height = x1 - x0 + margin.top + margin.bottom;

  const svg = d3
    .select(graphEl)
    .selectAll("svg")
    .data([null])
    .join("svg")
    .attr("viewBox", [0, 0, width, height])
    .attr("preserveAspectRatio", "xMinYMin meet");

  const canvas = svg
    .selectAll("g.canvas")
    .data([null])
    .join("g")
    .attr("class", "canvas")
    .attr("transform", `translate(${margin.left},${margin.top - x0})`);

  const gLinks = canvas.selectAll("g.links").data([null]).join("g").attr("class", "links");
  const gNodes = canvas.selectAll("g.nodes").data([null]).join("g").attr("class", "nodes");

  const linkPath = d3.linkHorizontal().x((d) => d.y).y((d) => d.x);
  const transition = svg.transition().duration(700).ease(d3.easeCubicInOut);

  const link = gLinks.selectAll("path").data(root.links(), (d) => d.target.data.id);
  link
    .join(
      (enter) =>
        enter
          .append("path")
          .attr("class", "link")
          .attr("d", linkPath)
          .attr("stroke-opacity", 0)
          .call((enter) => enter.transition(transition).attr("stroke-opacity", 1)),
      (update) => update.call((update) => update.transition(transition).attr("d", linkPath)),
      (exit) =>
        exit.call((exit) => exit.transition(transition).attr("stroke-opacity", 0).remove())
    );

  const node = gNodes.selectAll("g.node").data(root.descendants(), (d) => d.data.id);
  const nodeEnter = node
    .enter()
    .append("g")
    .attr("class", (d) => nodeClass(d))
    .attr("transform", (d) => `translate(${d.y},${d.x})`)
    .attr("opacity", 0);

  nodeEnter.append("circle").attr("r", (d) => nodeRadius(d));
  nodeEnter
    .append("text")
    .attr("dy", "0.32em")
    .attr("x", (d) => (d.children ? -14 : 14))
    .attr("text-anchor", (d) => (d.children ? "end" : "start"))
    .text((d) => d.data.name);

  nodeEnter
    .on("mouseenter", showTooltip)
    .on("mousemove", moveTooltip)
    .on("mouseleave", hideTooltip);

  node
    .merge(nodeEnter)
    .attr("class", (d) => nodeClass(d))
    .transition(transition)
    .attr("transform", (d) => `translate(${d.y},${d.x})`)
    .attr("opacity", 1);

  node.exit().transition(transition).attr("opacity", 0).remove();
}

function renderError(message) {
  graphEl.innerHTML = `<div class="muted">${message}</div>`;
}

async function loadData() {
  try {
    const [current, corrected, runtime] = await Promise.all([
      fetch(DATA_PATHS.current).then((res) => {
        if (!res.ok) throw new Error("Failed to load current hierarchy.");
        return res.json();
      }),
      fetch(DATA_PATHS.corrected).then((res) => {
        if (!res.ok) throw new Error("Failed to load corrected hierarchy.");
        return res.json();
      }),
      fetch(DATA_PATHS.runtime).then((res) => {
        if (!res.ok) throw new Error("Failed to load runtime manifest.");
        return res.json();
      }),
    ]);

    state.current = current;
    state.corrected = corrected;
    state.runtime = runtime;

    updateStats();
    updateCaseDetails();
    updateChangeList();
    render();
  } catch (error) {
    renderError("Could not load hierarchy JSON. Run `python app.py export` first.");
  }
}

viewButtons.forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

animateBtn.addEventListener("click", () => {
  setView("current");
  setTimeout(() => setView("corrected"), 700);
});

let resizeTimer;
window.addEventListener("resize", () => {
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(render, 200);
});

loadData();
