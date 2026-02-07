document.addEventListener("DOMContentLoaded", function () {
    const html = document.documentElement;
    const lightBtn = document.getElementById("lightModeBtn");
    const darkBtn = document.getElementById("darkModeBtn");

    // Function to update button states
    function updateButtons(theme) {
        if (theme === "dark") {
            lightBtn?.classList.remove("active");
            darkBtn?.classList.add("active");
        } else {
            darkBtn?.classList.remove("active");
            lightBtn?.classList.add("active");
        }
    }

    // Set theme on initial load from localStorage
    const savedTheme = localStorage.getItem("theme") || "light";
    html.setAttribute("data-bs-theme", savedTheme);
    updateButtons(savedTheme);

    // Event listener for light mode button
    lightBtn?.addEventListener("click", function () {
        html.setAttribute("data-bs-theme", "light");
        localStorage.setItem("theme", "light");
        updateButtons("light");
    });

    // Event listener for dark mode button
    darkBtn?.addEventListener("click", function () {
        html.setAttribute("data-bs-theme", "dark");
        localStorage.setItem("theme", "dark");
        updateButtons("dark");
    });
});