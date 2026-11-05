/* Month calendar built from index.json. Days with a record are highlighted and
   link to that day; the arrows move between months. On a day page the calendar
   opens on that day's month, otherwise on the current month. */
(function () {
  var mount = document.getElementById("calendar");
  if (!mount) return;

  var pageDate = document.body.dataset.date || null; // "YYYY-MM-DD" or null

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  fetch("./index.json")
    .then(function (r) {
      return r.json();
    })
    .then(function (list) {
      var have = {};
      list.forEach(function (e) {
        have[e.date] = true;
      });

      var view;
      if (pageDate) {
        var p = pageDate.split("-");
        view = new Date(Number(p[0]), Number(p[1]) - 1, 1);
      } else {
        var now = new Date();
        view = new Date(now.getFullYear(), now.getMonth(), 1);
      }

      var DOW = ["日", "月", "火", "水", "木", "金", "土"];

      function render() {
        var year = view.getFullYear();
        var month = view.getMonth();
        var startDow = new Date(year, month, 1).getDay();
        var days = new Date(year, month + 1, 0).getDate();

        var html = '<div class="cal-head">';
        html += '<button class="cal-nav" data-dir="-1" aria-label="前の月">‹</button>';
        html += '<span class="cal-title">' + year + "年" + (month + 1) + "月</span>";
        html += '<button class="cal-nav" data-dir="1" aria-label="次の月">›</button>';
        html += "</div><div class=\"cal-grid\">";

        DOW.forEach(function (w) {
          html += '<div class="cal-dow">' + w + "</div>";
        });
        for (var i = 0; i < startDow; i++) {
          html += '<div class="cal-cell empty"></div>';
        }
        for (var d = 1; d <= days; d++) {
          var key = year + "-" + pad(month + 1) + "-" + pad(d);
          var cls = "cal-cell";
          if (have[key]) cls += " has-record";
          if (key === pageDate) cls += " current";
          if (have[key] && key !== pageDate) {
            html += '<a class="' + cls + '" href="./' + key + '.html">' + d + "</a>";
          } else {
            html += '<div class="' + cls + '">' + d + "</div>";
          }
        }
        html += "</div>";
        mount.innerHTML = html;

        mount.querySelectorAll(".cal-nav").forEach(function (btn) {
          btn.addEventListener("click", function () {
            view = new Date(
              view.getFullYear(),
              view.getMonth() + Number(btn.dataset.dir),
              1
            );
            render();
          });
        });
      }

      render();
    });
})();
