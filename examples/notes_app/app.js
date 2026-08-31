/* 2066 Notes — UI shell. All logic happens in .ai programs server-side;
 * the browser stores only the session token, never a user id. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var token = null;

  function api(path, body) {
    return fetch(path, {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) { return r.json(); });
  }

  function showMessage(text, isError) {
    var el = $("auth-message");
    el.textContent = text;
    el.classList.toggle("error", !!isError);
  }

  function enterApp(t, username) {
    token = t;
    $("who").textContent = "— session active (" + username + ")";
    $("auth-view").hidden = true;
    $("app-view").hidden = false;
  }

  $("register").addEventListener("click", function () {
    api("/api/register", { username: $("username").value,
                           password: $("password").value })
      .then(function (data) {
        var ok = data.result.indexOf("ok:") === 0;
        showMessage(data.result, !ok);
        if (ok && data.token) enterApp(data.token, $("username").value);
      });
  });

  $("login").addEventListener("click", function () {
    api("/api/login", { username: $("username").value,
                        password: $("password").value })
      .then(function (data) {
        var ok = data.result.indexOf("ok:") === 0;
        showMessage(data.result, !ok);
        if (ok && data.token) enterApp(data.token, $("username").value);
      });
  });

  $("add").addEventListener("click", function () {
    api("/api/note", { token: token, title: $("title").value,
                       body: $("body").value })
      .then(function (data) {
        if (data.result.indexOf("ok:") === 0) {
          showMessage("note saved → " + data.result, false);
          $("note-id").value = data.result.slice(3);
        } else {
          showMessage(data.result, true);
        }
      });
  });

  $("list").addEventListener("click", function () {
    fetch("/api/notes?token=" + token)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.denied) {
          showMessage(data.result, true);
          return;
        }
        var el = $("note-view");
        el.textContent = data.titles.length
          ? data.titles.map(function (t, i) { return (i + 1) + ". " + t; })
              .join("\n")
          : "(no notes yet)";
        el.classList.remove("error");
      });
  });

  $("fetch").addEventListener("click", function () {
    fetch("/api/note?id=" + $("note-id").value + "&token=" + token)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var el = $("note-view");
        el.textContent = data.result;
        el.classList.toggle("error",
                            data.result.indexOf(" :: ") === -1);
      });
  });

  $("logout").addEventListener("click", function () {
    token = null;
    $("app-view").hidden = true;
    $("auth-view").hidden = false;
    $("note-view").textContent = "";
    showMessage("logged out (token discarded client-side)", false);
  });
})();
