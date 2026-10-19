// Your account: photo, name, gender, user id, email, password, delete account.
import { api, errorText, uploadFile } from "../api.js";
import { h, icon, render } from "../dom.js";
import { GENDERS, photoOf } from "../people.js";
import { errorLine, skeleton, toast } from "../ui.js";

/** Square-crop and shrink a picture in the browser, so only a small JPEG is uploaded. */
function shrink(file, size = 256) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const side = Math.min(img.naturalWidth, img.naturalHeight);
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, size, size);
      ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, size, size);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not read that picture."))), "image/jpeg", 0.86);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("That file is not a picture this browser can open."));
    };
    img.src = url;
  });
}

export default function profile(root, { me, refreshMe }) {
  if (me.via !== "account") {
    render(root, h("section", { class: "card" },
      h("h2", null, "Profile"),
      h("p", { class: "muted" }, "You signed in without a Mentora account (from Moodle or the demo sign-in), so there is no profile to edit.")));
    return undefined;
  }
  const st = { p: null, name: "", gender: "", busy: false, pw: { current: "", next: "", again: "" }, del: "" };

  async function load() {
    try {
      st.p = await api.get("/api/me/profile");
      st.name = st.p.name;
      st.gender = st.p.gender;
      paint();
    } catch (e) {
      render(root, errorLine(errorText(e)));
    }
  }

  async function act(fn, ok) {
    st.busy = true;
    paint();
    try {
      await fn();
      if (ok) toast(ok);
    } catch (e) {
      toast(errorText(e), "error");
    }
    st.busy = false;
    paint();
  }

  const pickPhoto = (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    act(async () => {
      const blob = await shrink(file);
      st.p = await uploadFile("/api/me/photo", new File([blob], "photo.jpg", { type: "image/jpeg" }));
      refreshMe();
    }, "Photo updated.");
  };

  const removePhoto = () => act(async () => {
    await api.del("/api/me/photo");
    st.p = await api.get("/api/me/profile");
    refreshMe();
  }, "Photo removed.");

  const saveDetails = (e) => {
    e.preventDefault();
    act(async () => {
      const r = await fetch("/api/me/profile", {
        method: "PATCH", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: st.name.trim(), gender: st.gender }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Could not save.");
      st.p = data;
      refreshMe();
    }, "Saved.");
  };

  const resend = () => act(() => api.post("/api/auth/resend-verification"), `We sent a new link to ${st.p.email}.`);

  const changePassword = (e) => {
    e.preventDefault();
    if (st.pw.next !== st.pw.again) {
      toast("The two new passwords are not the same.", "error");
      return;
    }
    act(async () => {
      await api.post("/api/me/password", { current: st.pw.current, new: st.pw.next });
      st.pw = { current: "", next: "", again: "" };
    }, "Password changed. Other devices are signed out.");
  };

  const deleteAccount = (e) => {
    e.preventDefault();
    if (!window.confirm("Delete your account and all your learning data? This cannot be undone.")) return;
    act(async () => {
      await api.post("/api/me/account/delete", { password: st.del });
      window.location.hash = "";
      window.location.reload();
    });
  };

  const pw = (key, label, auto) => h("label", { class: "field" }, h("span", null, label),
    h("input", {
      type: "password", value: st.pw[key], "data-key": `pw-${key}`, autocomplete: auto, required: true, maxlength: "128",
      onInput: (e) => { st.pw[key] = e.target.value; },
    }));

  function paint() {
    const p = st.p;
    render(root, h(
      "div", { class: "stack" },
      h("section", { class: "card" },
        h("div", { class: "profile-head" },
          photoOf({ ...p, has_photo: p.has_photo }, "big"),
          h("div", { style: { flex: 1, minWidth: 220 } },
            h("h2", { style: { margin: "0 0 2px" } }, p.name),
            h("div", { class: "muted" }, `@${p.username} · ${p.role === "teacher" ? "Teacher" : "Student"}`),
            h("div", { class: "row mt" },
              h("label", { class: `btn primary small ${st.busy ? "disabled" : ""}` }, icon("upload"), p.has_photo ? " Change photo" : " Add photo",
                h("input", { type: "file", accept: "image/*", hidden: true, disabled: st.busy, onChange: pickPhoto })),
              p.has_photo ? h("button", { class: "btn small", disabled: st.busy, onClick: removePhoto }, "Remove photo") : null),
            h("div", { class: "hint" }, p.role === "teacher"
              ? "Your photo is shown to your students and to students looking for their teacher."
              : "Your photo is shown only to you and your teachers.")))),

      h("div", { class: "grid cols-2" },
        h("section", { class: "card" },
          h("h2", null, "Your details"),
          h("form", { onSubmit: saveDetails },
            h("label", { class: "field" }, h("span", null, "Full name"),
              h("input", { type: "text", value: st.name, "data-key": "name", required: true, maxlength: "80", onInput: (e) => { st.name = e.target.value; } })),
            h("label", { class: "field" }, h("span", null, "Gender"),
              h("select", { onChange: (e) => { st.gender = e.target.value; } },
                GENDERS.map(([v, l]) => h("option", { value: v, selected: st.gender === v }, l)))),
            h("label", { class: "field" }, h("span", null, "User id"),
              h("input", { type: "text", value: p.username, disabled: true }),
              h("div", { class: "hint" }, "Your user id is permanent. Teachers and students find you by it.")),
            h("label", { class: "field" }, h("span", null, "Email"),
              h("input", { type: "email", value: p.email, disabled: true }),
              h("div", { class: `hint ${p.email_verified ? "ok" : "bad"}` },
                p.email_verified ? "✓ Confirmed" : "Not confirmed yet. ",
                !p.email_verified ? h("button", { type: "button", class: "link-btn inline", disabled: st.busy, onClick: resend }, "Send the link again") : null)),
            h("button", { class: "btn primary", type: "submit", disabled: st.busy }, "Save"))),
        h("section", { class: "card" },
          h("h2", null, "Password"),
          h("form", { onSubmit: changePassword },
            pw("current", "Current password", "current-password"),
            pw("next", "New password (at least 8 characters)", "new-password"),
            pw("again", "Confirm new password", "new-password"),
            h("button", { class: "btn primary", type: "submit", disabled: st.busy }, "Change password")))),

      h("section", { class: "card" },
        h("h2", null, "Delete account"),
        h("p", { class: "muted" },
          "This permanently deletes your account, photo and teacher connections",
          p.role === "learner" ? ", and all your learning data (sessions, answers, goals, notes)." : "."),
        h("form", { class: "row", onSubmit: deleteAccount },
          h("input", {
            type: "password", placeholder: "Your password", value: st.del, "data-key": "del", autocomplete: "current-password",
            required: true, style: { maxWidth: 260 }, onInput: (e) => { st.del = e.target.value; },
          }),
          h("button", { class: "btn danger", type: "submit", disabled: st.busy }, icon("trash"), " Delete my account"))),
    ));
  }

  render(root, skeleton({ cards: 2 }));
  load();
  return undefined;
}
