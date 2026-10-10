document.querySelectorAll(".toggle-password").forEach((toggle) => {

    const input = document.getElementById(toggle.dataset.target);

    if (!input) return;

    toggle.addEventListener("click", () => {

        if (input.type === "password") {

            input.type = "text";

            toggle.innerHTML = '<i class="bi bi-eye-slash"></i>';

        } else {

            input.type = "password";

            toggle.innerHTML = '<i class="bi bi-eye"></i>';

        }

    });

});

// "Remember Me" also applies to "Continue with Google" (ADR-87): the button
// is a plain link, so the checkbox state rides along as ?remember=1. Only
// that one parameter is touched - the link's `intent` is left as rendered.
const rememberMe = document.getElementById("rememberMe");

if (rememberMe) {

    document.querySelectorAll("a.btn-google").forEach((link) => {

        link.addEventListener("click", () => {

            const url = new URL(link.href, window.location.origin);

            if (rememberMe.checked) {

                url.searchParams.set("remember", "1");

            } else {

                url.searchParams.delete("remember");

            }

            link.href = url.toString();

        });

    });

}
