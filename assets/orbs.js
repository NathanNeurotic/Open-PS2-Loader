/* PS2 OSDSYS cursor orbs -- loaded on every page after app.js (moved out of index.html's inline
   script so the animation is not front-page only). Creates #ps2-orbs itself when a page has none. */
(function () {
  // Visitors who asked their system for reduced motion get no animation at all (and no canvas).
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  // One canvas per page. index.html used to carry it (and this whole script) inline, so the orbs
  // only ever ran on the front page; every page now loads this file after app.js.
  var canvas = document.getElementById('ps2-orbs');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'ps2-orbs';
    canvas.className = 'ps2-orbs-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.appendChild(canvas);
  }
  var ctx = canvas.getContext('2d');
  if (!ctx) return;

  var width = window.innerWidth;
  var height = window.innerHeight;
  var dpr = window.devicePixelRatio || 1;

  function resize() {
    dpr = window.devicePixelRatio || 1;
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
  }
  window.addEventListener('resize', resize);
  resize();

  var mouse = {
    x: width / 2,
    y: height / 2,
    targetX: width / 2,
    targetY: height / 2,
    speed: 0,
    hasMoved: false
  };

  function onPointerMove(x, y) {
    mouse.targetX = x;
    mouse.targetY = y;
    if (!mouse.hasMoved) {
      mouse.x = x;
      mouse.y = y;
      mouse.hasMoved = true;
    }
  }

  // mousemove bubbles from document to window, so one listener sees every move.
  window.addEventListener('mousemove', function (e) {
    onPointerMove(e.clientX, e.clientY);
  });

  window.addEventListener('touchmove', function (e) {
    if (e.touches && e.touches.length > 0) {
      onPointerMove(e.touches[0].clientX, e.touches[0].clientY);
    }
  }, { passive: true });

  // 7 authentic PS2 OSDSYS orbs with visible sizing
  var ORBS = [
    { radius: 36, speed: 0.038, tiltX: 0.65, tiltY: 0.35, phase: 0.0, size: 4.8, hue: 'cyan' },
    { radius: 52, speed: -0.028, tiltX: -0.55, tiltY: 0.50, phase: 1.1, size: 4.2, hue: 'blue' },
    { radius: 26, speed: 0.046, tiltX: 0.40, tiltY: -0.70, phase: 2.3, size: 3.8, hue: 'cyan' },
    { radius: 64, speed: -0.022, tiltX: 0.75, tiltY: -0.30, phase: 3.5, size: 5.2, hue: 'ice' },
    { radius: 44, speed: 0.032, tiltX: -0.70, tiltY: -0.45, phase: 4.4, size: 4.0, hue: 'blue' },
    { radius: 74, speed: 0.020, tiltX: 0.30, tiltY: 0.80, phase: 5.2, size: 4.6, hue: 'cyan' },
    { radius: 58, speed: -0.030, tiltX: -0.45, tiltY: -0.60, phase: 5.9, size: 3.9, hue: 'ice' }
  ];

  var orbStates = [];
  for (var i = 0; i < ORBS.length; i++) {
    orbStates.push({
      cfg: ORBS[i],
      angle: ORBS[i].phase,
      history: []
    });
  }

  // Trailing stardust particles emitted as cursor sweeps
  var particles = [];
  var lastTime = performance.now();

  function tick(now) {
    var dt = Math.min((now - lastTime) / 1000, 0.05);
    lastTime = now;
    // Everything below was tuned per 60 Hz frame; f scales it so 120/144 Hz screens move the same.
    var f = dt * 60;

    // Fluid spring cursor tracking (0.16 per 60 Hz frame, compounded for the real frame time)
    var dx = mouse.targetX - mouse.x;
    var dy = mouse.targetY - mouse.y;
    var follow = 1 - Math.pow(1 - 0.16, f);
    mouse.x += dx * follow;
    mouse.y += dy * follow;
    mouse.speed = Math.sqrt(dx * dx + dy * dy);

    // Spawn subtle stardust trail when cursor moves
    if (mouse.speed > 1.5 && particles.length < 40) {
      particles.push({
        x: mouse.x + (Math.random() - 0.5) * 12,
        y: mouse.y + (Math.random() - 0.5) * 12,
        vx: (Math.random() - 0.5) * 0.8 - (dx * 0.03),
        vy: (Math.random() - 0.5) * 0.8 - (dy * 0.03),
        life: 1.0,
        decay: 0.03 + Math.random() * 0.03,
        size: 1.5 + Math.random() * 2.2,
        hue: Math.random() > 0.4 ? 'cyan' : 'blue'
      });
    }

    // Ambient floating wave when resting
    var idleWaveX = Math.sin(now * 0.001) * 6;
    var idleWaveY = Math.cos(now * 0.0013) * 5;

    var cx = mouse.x + idleWaveX;
    var cy = mouse.y + idleWaveY;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 1. Update and render stardust particles
    for (var p = particles.length - 1; p >= 0; p--) {
      var pt = particles[p];
      pt.x += pt.vx * f;
      pt.y += pt.vy * f;
      pt.life -= pt.decay * f;
      if (pt.life <= 0) {
        particles.splice(p, 1);
        continue;
      }
      var pAlpha = pt.life * 0.85;
      var pColor = pt.hue === 'cyan'
        ? 'rgba(56, 189, 248, ' + pAlpha + ')'
        : 'rgba(96, 165, 250, ' + pAlpha + ')';
      ctx.fillStyle = pColor;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, pt.size * pt.life, 0, Math.PI * 2);
      ctx.fill();
    }

    // 2. Calculate 3D positions for the 7 satellite orbs
    var renderedOrbs = [];
    for (var k = 0; k < orbStates.length; k++) {
      var o = orbStates[k];
      o.angle += o.cfg.speed * (dt * 60);

      var rad = o.cfg.radius;
      var ox = Math.cos(o.angle) * rad;
      var oy = Math.sin(o.angle) * rad;

      // 3D rotation by inclined orbital plane
      var x3 = ox * Math.cos(o.cfg.tiltY) - oy * Math.sin(o.cfg.tiltX) * Math.sin(o.cfg.tiltY);
      var y3 = oy * Math.cos(o.cfg.tiltX);
      var z3 = ox * Math.sin(o.cfg.tiltY) + oy * Math.sin(o.cfg.tiltX) * Math.cos(o.cfg.tiltY);

      // Depth projection: front is brighter & larger, rear is dimmer & smaller
      var depth = (z3 + 90) / 180;
      depth = Math.max(0.25, Math.min(1.0, depth));

      var screenX = cx + x3;
      var screenY = cy + y3;

      // Update trail history
      o.history.unshift({ x: screenX, y: screenY, depth: depth });
      if (o.history.length > 7) {
        o.history.pop();
      }

      renderedOrbs.push({
        orb: o,
        x: screenX,
        y: screenY,
        z: z3,
        depth: depth,
        size: o.cfg.size * (0.75 + 0.55 * depth),
        hue: o.cfg.hue
      });
    }

    // Sort rear to front for correct depth order
    renderedOrbs.sort(function (a, b) { return a.z - b.z; });

    // 3. Draw ethereal motion trails for orbs
    for (var t = 0; t < renderedOrbs.length; t++) {
      var item = renderedOrbs[t];
      var hist = item.orb.history;
      if (hist.length > 1) {
        for (var h = 1; h < hist.length; h++) {
          var p0 = hist[h - 1];
          var p1 = hist[h];
          var trailAlpha = (1 - h / hist.length) * 0.45 * p1.depth;
          var trailCol = item.hue === 'blue'
            ? 'rgba(96, 165, 250, ' + trailAlpha + ')'
            : (item.hue === 'ice' ? 'rgba(224, 242, 254, ' + trailAlpha + ')' : 'rgba(56, 189, 248, ' + trailAlpha + ')');
          ctx.strokeStyle = trailCol;
          ctx.lineWidth = Math.max(0.9, item.size * 0.6 * (1 - h / hist.length));
          ctx.beginPath();
          ctx.moveTo(p0.x, p0.y);
          ctx.lineTo(p1.x, p1.y);
          ctx.stroke();
        }
      }
    }

    // 4. Draw glowing orb bodies
    for (var i = 0; i < renderedOrbs.length; i++) {
      var ro = renderedOrbs[i];
      var glowRadius = ro.size * 5.0;

      // Outer soft ambient glow
      var grad = ctx.createRadialGradient(ro.x, ro.y, 0, ro.x, ro.y, glowRadius);

      var colorCore = 'rgba(255, 255, 255, ' + (0.98 * ro.depth) + ')';
      var colorInner, colorOuter;

      if (ro.hue === 'blue') {
        colorInner = 'rgba(96, 165, 250, ' + (0.75 * ro.depth) + ')';
        colorOuter = 'rgba(30, 64, 175, 0)';
      } else if (ro.hue === 'ice') {
        colorInner = 'rgba(186, 230, 253, ' + (0.85 * ro.depth) + ')';
        colorOuter = 'rgba(56, 189, 248, 0)';
      } else { // cyan
        colorInner = 'rgba(56, 189, 248, ' + (0.85 * ro.depth) + ')';
        colorOuter = 'rgba(14, 116, 144, 0)';
      }

      grad.addColorStop(0, colorCore);
      grad.addColorStop(0.3, colorInner);
      grad.addColorStop(1, colorOuter);

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(ro.x, ro.y, glowRadius, 0, Math.PI * 2);
      ctx.fill();

      // Sharp intense center core
      ctx.fillStyle = colorCore;
      ctx.beginPath();
      ctx.arc(ro.x, ro.y, Math.max(1.5, ro.size * 0.45), 0, Math.PI * 2);
      ctx.fill();
    }

    // 5. Connect close orbs with subtle ethereal energy filaments
    for (var a = 0; a < renderedOrbs.length; a++) {
      for (var b = a + 1; b < renderedOrbs.length; b++) {
        var oA = renderedOrbs[a];
        var oB = renderedOrbs[b];
        var distSq = (oA.x - oB.x) * (oA.x - oB.x) + (oA.y - oB.y) * (oA.y - oB.y);
        var maxDist = 55;
        if (distSq < maxDist * maxDist) {
          var dist = Math.sqrt(distSq);
          var filamentAlpha = (1 - dist / maxDist) * 0.28 * Math.min(oA.depth, oB.depth);
          ctx.strokeStyle = 'rgba(56, 189, 248, ' + filamentAlpha + ')';
          ctx.lineWidth = 1.0;
          ctx.beginPath();
          ctx.moveTo(oA.x, oA.y);
          ctx.lineTo(oB.x, oB.y);
          ctx.stroke();
        }
      }
    }

    requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
})();
