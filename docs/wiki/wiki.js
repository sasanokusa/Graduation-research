(function () {
  var path = (location.pathname.split('/').pop() || 'index.html');
  var id = path === 'index.html' ? 'index' : path.slice(0, -5);
  var links = document.querySelectorAll('aside.sidebar a');
  for (var i = 0; i < links.length; i++) {
    if (links[i].getAttribute('data-id') === id) {
      links[i].classList.add('active');
    }
  }
})();
