const password = document.getElementById("password");
const toggle = document.getElementById("togglePassword");

toggle.addEventListener("click", () => {

    if (password.type === "password") {

        password.type = "text";

        toggle.innerHTML = '<i class="bi bi-eye-slash"></i>';

    } else {

        password.type = "password";

        toggle.innerHTML = '<i class="bi bi-eye"></i>';

    }

});