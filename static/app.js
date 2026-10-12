'use strict';
// All interactions stay in the browser; entries and files are saved by the private server.
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const menuToggle = $('[data-toggle-sidebar]');
const mobileNav = $('#mobile-nav');
menuToggle?.addEventListener('click', () => {
  if (!mobileNav) return;
  mobileNav.hidden = !mobileNav.hidden;
  menuToggle.setAttribute('aria-expanded', String(!mobileNav.hidden));
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && mobileNav && !mobileNav.hidden) {
    mobileNav.hidden = true;
    menuToggle?.setAttribute('aria-expanded', 'false');
    menuToggle?.focus();
  }
});
$('[data-password-toggle]')?.addEventListener('click', (e) => {
  const field = $('#password');
  if (!field) return;
  field.type = field.type === 'password' ? 'text' : 'password';
  e.currentTarget.textContent = field.type === 'password' ? 'Show' : 'Hide';
  e.currentTarget.setAttribute('aria-label', field.type === 'password' ? 'Show password' : 'Hide password');
});
$$('[data-confirm]').forEach(btn => btn.addEventListener('click', event => {
  if (!window.confirm(btn.dataset.confirm)) event.preventDefault();
}));
const photosInput = $('#photos');
const previews = $('#upload-previews');
const dropZone = $('#upload-zone');
if (photosInput && previews && dropZone) {
  const showPreviews = () => {
    previews.replaceChildren();
    const images = Array.from(photosInput.files);
    if (images.length > 12) { window.alert('Please choose no more than 12 photos at a time.'); photosInput.value=''; return; }
    images.forEach((file) => {
      const item = document.createElement('div'); item.className = 'upload-preview';
      const image = document.createElement('img');
      const label = document.createElement('span'); label.textContent = file.name;
      const blobURL = URL.createObjectURL(file); image.src = blobURL;
      image.onload = () => URL.revokeObjectURL(blobURL);
      image.onerror = () => URL.revokeObjectURL(blobURL);
      item.append(image, label); previews.append(item);
    });
  };
  photosInput.addEventListener('change', showPreviews);
  ['dragenter','dragover'].forEach(type => dropZone.addEventListener(type, event => {
    event.preventDefault(); dropZone.classList.add('dragging');
  }));
  ['dragleave','drop'].forEach(type => dropZone.addEventListener(type, event => {
    event.preventDefault(); dropZone.classList.remove('dragging');
  }));
  dropZone.addEventListener('drop', event => {
    if (event.dataTransfer?.files?.length) {
      photosInput.files = event.dataTransfer.files; showPreviews();
    }
  });
}
// Image viewer (works with keyboard and touch).
const galleryElements = $$('.gallery-item[data-lightbox-src]');
const lightbox = $('#lightbox');
if (lightbox && galleryElements.length) {
  const lightboxImage = $('.lightbox-image', lightbox);
  const counter = $('.lightbox-count', lightbox);
  const images = $$('.gallery-grid .gallery-item[data-lightbox-src]');
  const selectedImages = images.length ? images : galleryElements;
  let currentIndex = 0;
  let previousFocus = null;
  const show = (index) => {
    currentIndex = (index + selectedImages.length) % selectedImages.length;
    lightboxImage.src = selectedImages[currentIndex].dataset.lightboxSrc;
    counter.textContent = `${currentIndex + 1} of ${selectedImages.length}`;
  };
  const open = index => {
    previousFocus = document.activeElement;
    lightbox.hidden = false;
    document.body.style.overflow = 'hidden';
    show(index);
    $('.lightbox-close', lightbox)?.focus();
  };
  const close = () => {
    lightbox.hidden = true;
    lightboxImage.removeAttribute('src');
    document.body.style.overflow = '';
    previousFocus?.focus();
  };
  galleryElements.forEach((element) => {
    element.addEventListener('click', () => {
      const index = selectedImages.findIndex(item => item.dataset.lightboxSrc === element.dataset.lightboxSrc);
      open(Math.max(index, 0));
    });
  });
  $('.lightbox-close', lightbox).addEventListener('click', close);
  $('.lightbox-previous', lightbox).addEventListener('click', () => show(currentIndex - 1));
  $('.lightbox-next', lightbox).addEventListener('click', () => show(currentIndex + 1));
  lightbox.addEventListener('click', e => { if (e.target === lightbox) close(); });
  document.addEventListener('keydown', e => {
    if (lightbox.hidden) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft') show(currentIndex - 1);
    if (e.key === 'ArrowRight') show(currentIndex + 1);
  });
}

// Load a YouTube iframe only after the owner chooses to play it. This keeps
// third-party network requests off private diary pages until interaction.
$$('[data-load-youtube]').forEach(button => button.addEventListener('click', () => {
  const wrapper = button.closest('[data-youtube-embed]');
  if (!wrapper || wrapper.querySelector('iframe')) return;
  const embedUrl = wrapper.dataset.youtubeEmbed;
  if (!/^https:\/\/www\.youtube-nocookie\.com\/embed\/[A-Za-z0-9_-]{11}$/.test(embedUrl)) return;
  const iframe = document.createElement('iframe');
  iframe.className = 'youtube-iframe';
  iframe.src = embedUrl + '?autoplay=1';
  iframe.title = 'YouTube video — ' + (wrapper.dataset.videoTitle || 'journal entry');
  iframe.allow = 'accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; web-share';
  iframe.referrerPolicy = 'strict-origin-when-cross-origin';
  iframe.setAttribute('allowfullscreen', '');
  wrapper.replaceChildren(iframe);
}));
