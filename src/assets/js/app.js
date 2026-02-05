/*
Template Name: Urbix - Admin & Dashboard Template
Author: Pixeleyez
Website: https://pixeleyez.com/
File: app.js - Main application JavaScript
*/

"use strict";

// ==============================================================================
// BOOTSTRAP COMPONENTS INITIALIZATION
// ==============================================================================

/**
 * Initialize Bootstrap components (tooltips, popovers)
 * @param {string} selector - CSS selector for elements
 * @param {Function} Component - Bootstrap component class
 * @returns {Array} Array of initialized components
 */
function initializeBootstrapComponents(selector, Component) {
  const triggerList = document.querySelectorAll(selector);
  return [...triggerList].map((triggerEl) => new Component(triggerEl));
}

// Initialize all tooltips
const tooltips = initializeBootstrapComponents(
  '[data-bs-toggle="tooltip"]',
  bootstrap.Tooltip
);

// Initialize all popovers
const popovers = initializeBootstrapComponents(
  '[data-bs-toggle="popover"]',
  bootstrap.Popover
);

// ==============================================================================
// STICKY HEADER
// ==============================================================================

/**
 * Make header sticky on scroll
 */
function initializeStickyHeader() {
  const stickyMenu = document.getElementById("appHeader");
  
  if (!stickyMenu) {
    console.warn("Sticky header element not found");
    return;
  }

  const stickyOffset = stickyMenu.offsetTop;

  function toggleStickyMenu() {
    if (window.scrollY > stickyOffset) {
      stickyMenu.classList.add("sticky-scroll");
    } else {
      stickyMenu.classList.remove("sticky-scroll");
    }
  }

  window.addEventListener("scroll", toggleStickyMenu);
}

// ==============================================================================
// BUTTON LOADER
// ==============================================================================

/**
 * Initialize loading state for buttons with .btn-loader class
 */
function initializeButtonLoaders() {
  const loaderButtons = document.querySelectorAll(".btn-loader");

  loaderButtons.forEach((button) => {
    button.addEventListener("click", function (e) {
      const indicatorLabel = this.querySelector(".indicator-label");
      
      if (!indicatorLabel) {
        console.warn("Indicator label not found in button");
        return;
      }

      const originalText = indicatorLabel.textContent;
      const loadingText = this.getAttribute("data-loading-text") || "Loading...";

      // Show loading state
      this.classList.add("loading");
      indicatorLabel.textContent = loadingText;
      this.disabled = true;

      // Simulate async operation (remove this in production)
      setTimeout(() => {
        this.classList.remove("loading");
        indicatorLabel.textContent = originalText;
        this.disabled = false;
      }, 1500);
    });
  });
}

// ==============================================================================
// SEARCH FUNCTIONALITY
// ==============================================================================

/**
 * Update search results list
 * @param {Array} items - Array of menu items to display
 * @param {HTMLElement} searchList - Search results container
 */
function updateSearchResults(items, searchList) {
  searchList.innerHTML = ""; // Clear previous results

  if (items.length === 0) {
    searchList.innerHTML = `
      <li class="mt-3 mb-1">
        <div class="d-flex align-items-center flex-column justify-content-center gap-2 my-16">
          <i class="ri-file-info-line fs-1 text-muted"></i>
          <p class="suggestion-title mb-0 text-center">No results found</p>
        </div>
      </li>
    `;
    return;
  }

  items.forEach((item) => {
    const li = document.createElement("li");

    if (item.separator) {
      li.innerHTML = `<p class="suggestion-title mb-0">${item.separator}</p>`;
      li.classList.add("mt-3", "mb-1");
    } else {
      li.innerHTML = `
        <a href="${item.link}" class="text-body">
          <div class="d-flex align-items-center gap-2">
            <i class="${item.icon}"></i>
            ${item.name}
          </div>
        </a>
      `;
      li.classList.add("suggestion-item", "d-flex", "align-items-center");
    }

    searchList.appendChild(li);
  });
}

/**
 * Extract menu items from sidebar
 * @returns {Array} Array of menu items
 */
function extractMenuItems() {
  const allMenus = document.querySelectorAll(
    "#sidebar-simplebar ul.pe-main-menu.list-unstyled"
  );
  const menuItems = [];

  allMenus.forEach((menu) => {
    const items = menu.querySelectorAll("li");

    items.forEach((item) => {
      const anchor = item.querySelector("a");
      
      if (!anchor) return;

      const href = anchor.getAttribute("href");
      
      // Check if it's a separator (dropdown menu)
      if (href && href.includes("#")) {
        menuItems.push({
          separator: anchor.textContent.trim(),
          name: "",
        });
      } else {
        const icon = item.querySelector("i");
        menuItems.push({
          name: anchor.textContent.trim(),
          icon: icon ? icon.className : "ri-circle-line pe-nav-icon fs-10",
          link: href || "#",
        });
      }
    });
  });

  return menuItems;
}

/**
 * Initialize search functionality
 */
function initializeSearch() {
  const searchInputInModal = document.getElementById("searchInputInModal");
  const searchList = document.getElementById("searchList");

  if (!searchInputInModal || !searchList) {
    console.warn("Search elements not found");
    return;
  }

  const menuItems = extractMenuItems();

  // Display all items initially
  updateSearchResults(menuItems, searchList);

  // Filter on input
  searchInputInModal.addEventListener("input", function () {
    const searchText = this.value.toLowerCase().trim();
    
    const filteredItems = searchText
      ? menuItems.filter((item) =>
          item.name.toLowerCase().includes(searchText)
        )
      : menuItems;

    updateSearchResults(filteredItems, searchList);
  });
}

// ==============================================================================
// HORIZONTAL MENU
// ==============================================================================

/**
 * Initialize horizontal menu collapse behavior
 */
function initializeHorizontalMenu() {
  const horizontalMenus = document.getElementById("horizontal-menu");

  if (!horizontalMenus) return;

  const horizontalMenuItems = horizontalMenus.querySelectorAll("nav > ul > li > a");

  horizontalMenuItems.forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();

      setTimeout(() => {
        item.setAttribute("aria-expanded", "false");
        item.classList.remove("collapsed");
        
        const submenu = item.nextElementSibling;
        if (submenu) {
          submenu.classList.remove("show");
        }
      }, 300);
    });
  });
}

// ==============================================================================
// SIDEBAR TOGGLE
// ==============================================================================

/**
 * Initialize sidebar toggle functionality
 */
function initializeSidebarToggle() {
  const sidebarToggle = document.getElementById("sidebarToggle");
  const sidebar = document.getElementById("sidebar");

  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", () => {
      sidebar.classList.toggle("collapsed");
      document.body.classList.toggle("sidebar-collapsed");
    });
  }
}

// ==============================================================================
// THEME TOGGLE (Dark/Light Mode)
// ==============================================================================

/**
 * Initialize theme toggle
 */
function initializeThemeToggle() {
  const themeToggle = document.getElementById("themeToggle");
  const currentTheme = localStorage.getItem("theme") || "light";

  // Set initial theme
  document.documentElement.setAttribute("data-theme", currentTheme);

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const theme = document.documentElement.getAttribute("data-theme");
      const newTheme = theme === "light" ? "dark" : "light";
      
      document.documentElement.setAttribute("data-theme", newTheme);
      localStorage.setItem("theme", newTheme);
    });
  }
}

// ==============================================================================
// FORM VALIDATION
// ==============================================================================

/**
 * Initialize Bootstrap form validation
 */
function initializeFormValidation() {
  const forms = document.querySelectorAll(".needs-validation");

  Array.from(forms).forEach((form) => {
    form.addEventListener(
      "submit",
      (event) => {
        if (!form.checkValidity()) {
          event.preventDefault();
          event.stopPropagation();
        }
        form.classList.add("was-validated");
      },
      false
    );
  });
}

// ==============================================================================
// MAIN INITIALIZATION
// ==============================================================================

/**
 * Initialize all app features
 */
function initializeApp() {
  initializeStickyHeader();
  initializeButtonLoaders();
  initializeSearch();
  initializeHorizontalMenu();
  initializeSidebarToggle();
  initializeThemeToggle();
  initializeFormValidation();

  console.log("Urbix app initialized successfully");
}

// Initialize when DOM is ready
document.addEventListener("DOMContentLoaded", initializeApp);

// ==============================================================================
// UTILITY FUNCTIONS
// ==============================================================================

/**
 * Show toast notification
 * @param {string} message - Message to display
 * @param {string} type - Type of toast (success, error, warning, info)
 */
function showToast(message, type = "info") {
  // Implement toast notification
  console.log(`[${type.toUpperCase()}] ${message}`);
}

/**
 * Confirm dialog
 * @param {string} message - Confirmation message
 * @returns {boolean} User confirmation
 */
function confirmAction(message) {
  return confirm(message);
}

// Export functions for use in other scripts
window.urbixApp = {
  showToast,
  confirmAction,
};