document.addEventListener("DOMContentLoaded", () => {

    const form = document.getElementById("libraryProfileForm");
    if (!form) return;

    // ------------------------------------------------------------------
    // Toast
    // ------------------------------------------------------------------

    function showToast(message, isError) {
        const toastEl = document.getElementById("settingsToast");
        const body = document.getElementById("settingsToastBody");
        if (!toastEl || !body || typeof bootstrap === "undefined") return;

        toastEl.classList.remove("text-bg-success", "text-bg-danger");
        toastEl.classList.add(isError ? "text-bg-danger" : "text-bg-success");
        body.textContent = (isError ? "⚠ " : "✓ ") + message;

        bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 2000, autohide: true }).show();
    }

    // ------------------------------------------------------------------
    // Field validation helpers
    // ------------------------------------------------------------------

    function setFieldError(input, hasError) {
        if (!input) return;
        input.classList.toggle("is-invalid", !!hasError);
    }

    const libraryNameInput = form.querySelector('[name="library_name"]');
    const ownerNameInput = form.querySelector('[name="owner_name"]');
    const phoneInput = form.querySelector('[name="phone"]');
    const emailInput = form.querySelector('[name="email"]');
    const openingTime = document.getElementById("openingTime");
    const closingTime = document.getElementById("closingTime");
    const timeError = document.getElementById("timeError");

    const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

    phoneInput?.addEventListener("input", () => {
        const digitsOnly = phoneInput.value.replace(/\D/g, "");
        if (digitsOnly !== phoneInput.value) phoneInput.value = digitsOnly;
        setFieldError(phoneInput, false);
    });

    emailInput?.addEventListener("input", () => setFieldError(emailInput, false));
    libraryNameInput?.addEventListener("input", () => setFieldError(libraryNameInput, false));
    ownerNameInput?.addEventListener("input", () => setFieldError(ownerNameInput, false));

    function validateTimes() {
        if (!openingTime || !closingTime || !timeError) return true;

        if (!openingTime.value || !closingTime.value) {
            timeError.classList.add("d-none");
            setFieldError(openingTime, false);
            setFieldError(closingTime, false);
            return true;
        }

        const isValid = openingTime.value < closingTime.value;
        timeError.classList.toggle("d-none", isValid);
        setFieldError(openingTime, !isValid);
        setFieldError(closingTime, !isValid);
        return isValid;
    }

    openingTime?.addEventListener("change", validateTimes);
    closingTime?.addEventListener("change", validateTimes);

    function validateBeforeSubmit() {
        let isValid = true;

        if (libraryNameInput && !libraryNameInput.value.trim()) {
            setFieldError(libraryNameInput, true);
            isValid = false;
        }

        if (ownerNameInput && !ownerNameInput.value.trim()) {
            setFieldError(ownerNameInput, true);
            isValid = false;
        }

        if (phoneInput) {
            const phoneValue = phoneInput.value.trim();
            if (!phoneValue || !/^\d+$/.test(phoneValue)) {
                setFieldError(phoneInput, true);
                isValid = false;
            }
        }

        if (emailInput && emailInput.value.trim() && !EMAIL_PATTERN.test(emailInput.value.trim())) {
            setFieldError(emailInput, true);
            isValid = false;
        }

        if (!validateTimes()) {
            isValid = false;
        }

        return isValid;
    }

    // ------------------------------------------------------------------
    // Logo upload / preview / remove
    // ------------------------------------------------------------------

    const logoInput = document.getElementById("logoInput");
    const removeLogoBtn = document.getElementById("removeLogoBtn");
    const removeLogoFlag = document.getElementById("removeLogoFlag");

    function showLogoImage(src) {
        let preview = document.getElementById("logoPreview");

        if (preview.tagName !== "IMG") {
            const img = document.createElement("img");
            img.id = "logoPreview";
            img.className = "settings-logo-circle";
            img.alt = "Library Logo";
            preview.replaceWith(img);
            preview = img;
        }

        preview.src = src;
    }

    function showLogoPlaceholder() {
        const preview = document.getElementById("logoPreview");
        if (preview && preview.tagName === "IMG") {
            const placeholder = document.createElement("div");
            placeholder.id = "logoPreview";
            placeholder.className = "settings-logo-circle-empty";
            placeholder.innerHTML = '<i class="bi bi-building"></i>';
            preview.replaceWith(placeholder);
        }
    }

    logoInput?.addEventListener("change", () => {
        const file = logoInput.files[0];
        if (!file) return;

        if (removeLogoFlag) removeLogoFlag.value = "0";

        const reader = new FileReader();
        reader.onload = (event) => showLogoImage(event.target.result);
        reader.readAsDataURL(file);
    });

    removeLogoBtn?.addEventListener("click", () => {
        if (!confirm("Remove the library logo? This cannot be undone.")) return;

        const finishLocalRemoval = () => {
            if (logoInput) logoInput.value = "";
            if (removeLogoFlag) removeLogoFlag.value = "1";
            showLogoPlaceholder();
            form.dataset.hasLogo = "0";
        };

        if (form.dataset.hasLogo === "1") {
            const url = form.dataset.removeLogoUrl;

            fetch(url, {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            })
                .then((response) => response.json())
                .then((data) => {
                    if (data.success) {
                        finishLocalRemoval();
                        showToast("Logo removed successfully.", false);
                    } else {
                        showToast(data.message || "Could not remove logo.", true);
                    }
                })
                .catch(() => showToast("Could not remove logo.", true));
        } else {
            finishLocalRemoval();
        }
    });

    // ------------------------------------------------------------------
    // Signature / Stamp upload / preview
    // ------------------------------------------------------------------

    function wireDocUpload(inputId, filenameId, previewWrapId) {
        const input = document.getElementById(inputId);
        const filenameEl = document.getElementById(filenameId);
        const wrap = document.getElementById(previewWrapId);
        if (!input) return;

        input.addEventListener("change", () => {
            const file = input.files[0];
            if (!file) return;

            setFieldError(input, false);
            if (filenameEl) filenameEl.textContent = file.name;

            const reader = new FileReader();
            reader.onload = (event) => {
                let img = wrap?.querySelector("img");
                if (!img && wrap) {
                    img = document.createElement("img");
                    img.className = "settings-doc-preview-img";
                    img.alt = "Preview";
                    wrap.appendChild(img);
                }
                if (img) img.src = event.target.result;
            };
            reader.readAsDataURL(file);
        });
    }

    wireDocUpload("signatureInput", "signatureFilename", "signaturePreviewWrap");
    wireDocUpload("stampInput", "stampFilename", "stampPreviewWrap");

    // ------------------------------------------------------------------
    // Save button state
    // ------------------------------------------------------------------

    const saveBtn = document.getElementById("saveChangesBtn");
    const saveSpinner = document.getElementById("saveSpinner");
    const saveIcon = document.getElementById("saveIcon");
    const saveButtonText = document.getElementById("saveButtonText");

    function setSaving(isSaving) {
        if (!saveBtn) return;
        saveBtn.disabled = isSaving;
        saveSpinner?.classList.toggle("d-none", !isSaving);
        saveIcon?.classList.toggle("d-none", isSaving);
        if (saveButtonText) saveButtonText.textContent = isSaving ? "Saving..." : "Save Changes";
    }

    // ------------------------------------------------------------------
    // Submit via AJAX - no page reload
    // ------------------------------------------------------------------

    form.addEventListener("submit", (event) => {
        event.preventDefault();

        if (!validateBeforeSubmit()) {
            showToast("Please fix the highlighted fields.", true);
            return;
        }

        setSaving(true);

        fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: { "X-Requested-With": "XMLHttpRequest" }
        })
            .then((response) => response.json().then((data) => ({ status: response.status, data })))
            .then(({ status, data }) => {
                if (status === 200 && data.success) {
                    showToast(data.message || "Library Profile Updated Successfully", false);

                    if (data.settings) {
                        const nameEl = document.getElementById("metaLibraryName");
                        const regEl = document.getElementById("metaRegDate");
                        const updatedEl = document.getElementById("metaLastUpdated");
                        if (nameEl) nameEl.textContent = data.settings.library_name || "—";
                        if (regEl) regEl.textContent = data.settings.registration_date || "—";
                        if (updatedEl) updatedEl.textContent = data.settings.last_updated || "—";

                        if (data.settings.logo_url) {
                            form.dataset.hasLogo = "1";
                        }

                        if (data.settings.stamp_filename) {
                            const stampFilenameEl = document.getElementById("stampFilename");
                            if (stampFilenameEl) stampFilenameEl.textContent = data.settings.stamp_filename;
                        }

                        if (data.settings.signature_filename) {
                            const signatureFilenameEl = document.getElementById("signatureFilename");
                            if (signatureFilenameEl) signatureFilenameEl.textContent = data.settings.signature_filename;
                        }
                    }

                    if (removeLogoFlag) removeLogoFlag.value = "0";
                } else {
                    const fieldMap = {
                        library_name: libraryNameInput,
                        owner_name: ownerNameInput,
                        phone: phoneInput,
                        email: emailInput,
                        opening_time: openingTime,
                        closing_time: closingTime,
                        logo: logoInput,
                        stamp: document.getElementById("stampInput"),
                        signature: document.getElementById("signatureInput")
                    };

                    if (data.errors) {
                        Object.keys(data.errors).forEach((field) => {
                            setFieldError(fieldMap[field], true);
                        });

                        if (data.errors.closing_time && timeError) {
                            timeError.textContent = data.errors.closing_time;
                            timeError.classList.remove("d-none");
                            setFieldError(openingTime, true);
                            setFieldError(closingTime, true);
                        }
                    }

                    showToast(data.message || "Something went wrong. Please try again.", true);
                }
            })
            .catch(() => showToast("Something went wrong. Please try again.", true))
            .finally(() => setSaving(false));
    });

});
