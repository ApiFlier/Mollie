/**
 * Weekend range calculation tests — run with: node tests/test_weekend.js
 * No dependencies. Tests the exact same logic used in js/events.js.
 */

function localDateStr(d) {
  var y = d.getFullYear();
  var m = String(d.getMonth() + 1).padStart(2, "0");
  var day = String(d.getDate()).padStart(2, "0");
  return y + "-" + m + "-" + day;
}

// Mirror of thisWeekendRange() in events.js, accepts optional refDate for testing.
function thisWeekendRange(refDate) {
  var today = refDate || new Date();
  var dow = today.getDay(); // 0=Sun, 1=Mon, …, 6=Sat
  var start, end;
  if (dow === 0) {
    // Sunday → today only
    start = new Date(today); end = new Date(today);
  } else if (dow >= 1 && dow <= 4) {
    // Mon–Thu → next Fri through next Sun
    start = new Date(today); start.setDate(today.getDate() + (5 - dow));
    end = new Date(start);   end.setDate(start.getDate() + 2);
  } else if (dow === 5) {
    // Friday → today through Sunday
    start = new Date(today); end = new Date(today); end.setDate(today.getDate() + 2);
  } else {
    // Saturday → today through Sunday
    start = new Date(today); end = new Date(today); end.setDate(today.getDate() + 1);
  }
  return { start: localDateStr(start), end: localDateStr(end) };
}

// ── Test harness ─────────────────────────────────────────────────────────────
var passed = 0, failed = 0;
function test(label, fn) {
  try { fn(); console.log("  PASS: " + label); passed++; }
  catch (e) { console.log("  FAIL: " + label + " — " + e.message); failed++; }
}
function eq(a, b) { if (a !== b) throw new Error("expected " + JSON.stringify(b) + " got " + JSON.stringify(a)); }

// ── Cases (verified against calendar: Jan 1 2026 = Thursday, dow=4) ──────────
// May 2026: May 1 = Fri, so:
//   May 15 = Fri (dow=5), May 16 = Sat, May 17 = Sun, May 18 = Mon
//   May 22 = Fri

test("Monday May 18 → Fri May 22 – Sun May 24", function () {
  var r = thisWeekendRange(new Date(2026, 4, 18)); // month 0-indexed
  eq(r.start, "2026-05-22"); eq(r.end, "2026-05-24");
});
test("Tuesday May 19 → Fri May 22 – Sun May 24", function () {
  var r = thisWeekendRange(new Date(2026, 4, 19));
  eq(r.start, "2026-05-22"); eq(r.end, "2026-05-24");
});
test("Wednesday May 20 → Fri May 22 – Sun May 24", function () {
  var r = thisWeekendRange(new Date(2026, 4, 20));
  eq(r.start, "2026-05-22"); eq(r.end, "2026-05-24");
});
test("Thursday May 21 → Fri May 22 – Sun May 24", function () {
  var r = thisWeekendRange(new Date(2026, 4, 21));
  eq(r.start, "2026-05-22"); eq(r.end, "2026-05-24");
});
test("Friday May 15 → May 15 – May 17", function () {
  var r = thisWeekendRange(new Date(2026, 4, 15));
  eq(r.start, "2026-05-15"); eq(r.end, "2026-05-17");
});
test("Saturday May 16 → May 16 – May 17", function () {
  var r = thisWeekendRange(new Date(2026, 4, 16));
  eq(r.start, "2026-05-16"); eq(r.end, "2026-05-17");
});
test("Sunday May 17 → May 17 only", function () {
  var r = thisWeekendRange(new Date(2026, 4, 17));
  eq(r.start, "2026-05-17"); eq(r.end, "2026-05-17");
});
// Verify start/end are always in the right order and end >= start
test("End date is always >= start date for all cases", function () {
  [0,1,2,3,4,5,6].forEach(function (dow) {
    // Find a date with the right day-of-week
    var base = new Date(2026, 4, 17); // Sun May 17
    var d = new Date(base); d.setDate(base.getDate() + dow);
    var r = thisWeekendRange(d);
    if (r.end < r.start) throw new Error("dow=" + dow + " end " + r.end + " < start " + r.start);
  });
});

console.log("\n" + passed + " passed, " + failed + " failed");
process.exit(failed > 0 ? 1 : 0);
