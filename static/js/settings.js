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

// ------------------------------------------------------------------
// Receipt Settings - live preview
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

    const form = document.getElementById("receiptSettingsForm");
    if (!form) return;

    const prefixInput = document.getElementById("receiptPrefixInput");
    const startingNumberInput = document.getElementById("startingReceiptNumberInput");
    const paperSizeSelect = document.getElementById("paperSizeSelect");
    const footerInput = document.getElementById("receiptFooterInput");

    const printLogo = document.getElementById("print_logo");
    const printStamp = document.getElementById("print_stamp");
    const printSignature = document.getElementById("print_signature");

    const numberPreviewEls = [
        document.getElementById("receiptNumberPreview"),
        document.getElementById("previewReceiptNumber")
    ].filter(Boolean);

    const previewCard = document.getElementById("receiptPreviewCard");
    const previewLogoWrap = document.getElementById("previewLogoWrap");
    const previewStampWrap = document.getElementById("previewStampWrap");
    const previewSignatureWrap = document.getElementById("previewSignatureWrap");
    const previewFooter = document.getElementById("previewFooter");
    const footerCharCount = document.getElementById("footerCharCount");

    // ------------------------------------------------------------------
    // Receipt Prefix - force uppercase, strip disallowed characters
    // ------------------------------------------------------------------

    function sanitizePrefix() {
        if (!prefixInput) return;
        const sanitized = prefixInput.value.toUpperCase().replace(/[^A-Z0-9-]/g, "").slice(0, 10);
        if (sanitized !== prefixInput.value) prefixInput.value = sanitized;
    }

    prefixInput?.addEventListener("input", sanitizePrefix);

    function formattedReceiptNumber() {
        const prefix = (prefixInput?.value || "LIB").trim() || "LIB";
        const rawNumber = parseInt(startingNumberInput?.value, 10);
        const number = Number.isFinite(rawNumber) && rawNumber > 0 ? rawNumber : 1;
        return `${prefix}-${String(number).padStart(5, "0")}`;
    }

    function toggleMark(wrap, show) {
        if (!wrap) return;
        const img = wrap.querySelector("img");
        wrap.style.visibility = (img && show) ? "visible" : "hidden";
    }

    function updatePreview() {
        const text = formattedReceiptNumber();
        numberPreviewEls.forEach((el) => { el.textContent = text; });

        toggleMark(previewLogoWrap, printLogo ? printLogo.checked : true);
        toggleMark(previewStampWrap, printStamp ? printStamp.checked : true);
        toggleMark(previewSignatureWrap, printSignature ? printSignature.checked : true);

        if (previewFooter) {
            const footerText = (footerInput?.value || "").trim();
            previewFooter.textContent = footerText || "Thank you for visiting!";
        }

        if (footerCharCount && footerInput) {
            footerCharCount.textContent = footerInput.value.length;
        }

        if (previewCard && paperSizeSelect) {
            previewCard.classList.toggle("receipt-preview-thermal", paperSizeSelect.value.startsWith("thermal"));
        }
    }

    [prefixInput, startingNumberInput, printLogo, printStamp, printSignature, paperSizeSelect, footerInput]
        .filter(Boolean)
        .forEach((el) => el.addEventListener("input", updatePreview));

    updatePreview();

});

// ------------------------------------------------------------------
// Notification Settings - quiet hours enable/disable time inputs
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

    const form = document.getElementById("notificationSettingsForm");
    if (!form) return;

    const quietHoursEnabled = document.getElementById("quiet_hours_enabled");
    const quietHoursStart = document.getElementById("quiet_hours_start");
    const quietHoursEnd = document.getElementById("quiet_hours_end");

    function toggleQuietHoursInputs() {
        const enabled = !!quietHoursEnabled?.checked;
        [quietHoursStart, quietHoursEnd].forEach((input) => {
            if (input) input.disabled = !enabled;
        });
    }

    quietHoursEnabled?.addEventListener("change", toggleQuietHoursInputs);
    toggleQuietHoursInputs();

});

// ------------------------------------------------------------------
// Security Settings - new/confirm password match check
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

    const form = document.getElementById("securityPasswordForm");
    if (!form) return;

    const newPasswordInput = document.getElementById("newPasswordInput");
    const confirmPasswordInput = document.getElementById("confirmPasswordInput");
    const mismatchError = document.getElementById("passwordMismatchError");

    function validateMatch() {
        const mismatch = !!confirmPasswordInput.value && newPasswordInput.value !== confirmPasswordInput.value;
        confirmPasswordInput.classList.toggle("is-invalid", mismatch);
        mismatchError?.classList.toggle("d-none", !mismatch);
        return !mismatch;
    }

    newPasswordInput?.addEventListener("input", validateMatch);
    confirmPasswordInput?.addEventListener("input", validateMatch);

    form.addEventListener("submit", (event) => {
        if (!validateMatch()) {
            event.preventDefault();
        }
    });

});
