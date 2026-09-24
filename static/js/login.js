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
