const strikeTime = 1.16;
const duration = 2.42;

const vertexShader = `
attribute vec2 position;
varying vec2 screen;
void main() {
  screen = position * .5 + .5;
  gl_Position = vec4(position, 0., 1.);
}
`;

const fragmentShader = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 screen;
uniform float time;
uniform float aspect;
uniform float strike;
uniform sampler2D lightning;

float hash(vec2 p) {
  vec3 v = fract(vec3(p.xyx) * vec3(.1031, .11369, .13787));
  v += dot(v, v.yzx + 19.19);
  return fract((v.x + v.y) * v.z);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 w = f * f * (3. - 2. * f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), w.x),
             mix(hash(i + vec2(0., 1.)), hash(i + 1.), w.x), w.y);
}

float cloud(vec2 p) {
  mat2 turn = mat2(.86, .51, -.51, .86);
  float value = .54 * noise(p);
  p = 2.07 * turn * p + 3.3;
  value += .26 * noise(p);
  p = 2.03 * turn * p - 4.1;
  value += .13 * noise(p);
  return value + .07 * noise(2.13 * turn * p + 1.9);
}

void main() {
  vec2 p = (screen - .5) * vec2(aspect, 1.);
  vec2 drift = vec2(.42, -.14) * time;
  vec2 bend = vec2(cloud(p * 2.1 - .55 * drift + 2.7),
                   cloud(p * 2.5 + .46 * drift - 4.5));
  vec2 air = p * vec2(2.8, 3.6) - drift + 1.55 * bend;
  float body = cloud(air);
  float curl = cloud(air * 1.84 - drift + vec2(3.5, -.8));
  float density = mix(body, curl, .29);
  float shade = cloud(air + vec2(-.31, .33));

  // The two layers reach different parts of the page at different times.
  float edge = time + .32 * screen.y - .42 * screen.x + (bend.x - .5) * .94;
  float threshold = mix(.71, .22, smoothstep(.03, 1.20, edge));
  float bank = smoothstep(threshold - .06, threshold + .30, density);
  float veil = .34 * smoothstep(.37, .78, curl)
                    * smoothstep(.12, .9, time - .25 * screen.y + .22 * screen.x);
  float stormPeak = smoothstep(.74, 1.16, time) * (1. - smoothstep(1.44, 1.98, time));
  float clearing = time + .25 * (bend.y - .5) + .15 * screen.x;
  float dissolve = 1. - smoothstep(1.61, 2.42, clearing);
  float cover = mix(max(bank * .94, veil), .97, stormPeak * .89)
                * smoothstep(.02, .32, time) * dissolve;

  float rim = smoothstep(-.13, .21, body - shade + .13 * (curl - .5));
  vec3 colour = mix(vec3(.061, .071, .085), vec3(.32, .355, .396), rim);
  colour *= mix(1.11, .77, smoothstep(.37, .73, density));

  // A local glow lights the cloud ridges around the single strike.
  vec2 light = (screen - vec2(.56, .56)) * vec2(aspect, 1.);
  float halo = exp(-dot(light, light) * 7.);
  colour += vec3(.18, .25, .34) * halo * strike * (.42 + .58 * rim);

  vec4 bolt = texture2D(lightning, screen);
  float filament = bolt.a * strike * (1. - .43 * smoothstep(.44, .77, density));
  gl_FragColor = vec4(bolt.rgb * filament + colour * cover * (1. - filament),
                      filament + cover * (1. - filament));
}
`;

type Point = [number, number];

function makeLightning(layer: HTMLCanvasElement, width: number, height: number) {
  const context = layer.getContext('2d');
  if (!context) return;
  layer.width = width;
  layer.height = height;
  const radius = Math.min(width, height);
  let seed = 864;
  const jitter = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296 - .5;
  };

  function split(from: Point, to: Point, divisions: number, roughness: number): Point[] {
    if (!divisions) return [from, to];
    const dx = to[0] - from[0];
    const dy = to[1] - from[1];
    const middle: Point = [
      (from[0] + to[0]) / 2 + dy * jitter() * roughness,
      (from[1] + to[1]) / 2 - dx * jitter() * roughness,
    ];
    return [...split(from, middle, divisions - 1, roughness).slice(0, -1),
      ...split(middle, to, divisions - 1, roughness)];
  }

  const main = split([width * .67, -height * .04], [width * .43, height * .84], 7, .70);
  const channels = [{ points: main, strength: 1 }];
  for (const [index, sideways, downward] of [
    [15, .38, .18], [32, -.64, .24], [48, .51, .26], [67, -.38, .30],
    [89, .44, .20], [106, -.27, .18],
  ]) {
    const start = main[index];
    const fork = split(start, [start[0] + sideways * radius, start[1] + downward * height], 5, .86);
    channels.push({ points: fork, strength: .47 });
    const junction = fork[12];
    channels.push({
      points: split(junction, [junction[0] + sideways * radius * .24, junction[1] + height * .14], 4, .96),
      strength: .26,
    });
  }

  context.lineJoin = 'round';
  context.lineCap = 'round';
  for (const { points, strength } of channels) {
    for (const [stroke, thickness, glow] of [
      ['rgba(96,169,243,.33)', .009, .022],
      ['rgba(155,210,255,.69)', .0045, .009],
      ['#eaf4ff', .0022, 0],
    ] as const) {
      context.strokeStyle = stroke;
      context.shadowColor = stroke;
      context.shadowBlur = radius * glow;
      context.lineWidth = Math.max(.47, radius * thickness * strength);
      context.beginPath();
      points.forEach(([x, y], index) => index ? context.lineTo(x, y) : context.moveTo(x, y));
      context.stroke();
    }
  }
}

function createProgram(gl: WebGLRenderingContext) {
  const program = gl.createProgram();
  if (!program) return null;
  for (const [type, source] of [[gl.VERTEX_SHADER, vertexShader], [gl.FRAGMENT_SHADER, fragmentShader]] as const) {
    const shader = gl.createShader(type);
    if (shader) {
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      gl.attachShader(program, shader);
      gl.deleteShader(shader);
    }
  }
  gl.linkProgram(program);
  if (gl.getProgramParameter(program, gl.LINK_STATUS)) return program;
  gl.deleteProgram(program);
  return null;
}

export function playStorm(canvas: HTMLCanvasElement, onStrike: () => void, onEnd: () => void) {
  const context = canvas.getContext('webgl', { alpha: true, antialias: false, depth: false, stencil: false });
  if (!context) return null;
  const gl = context;
  const program = createProgram(gl);
  const points = gl.createBuffer();
  const bolt = gl.createTexture();
  const release = () => {
    gl.deleteTexture(bolt);
    gl.deleteBuffer(points);
    gl.deleteProgram(program);
  };
  if (!program || !points || !bolt) {
    release();
    return null;
  }

  const position = gl.getAttribLocation(program, 'position');
  const elapsed = gl.getUniformLocation(program, 'time');
  const ratio = gl.getUniformLocation(program, 'aspect');
  const pulse = gl.getUniformLocation(program, 'strike');
  gl.useProgram(program);
  gl.bindBuffer(gl.ARRAY_BUFFER, points);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.bindTexture(gl.TEXTURE_2D, bolt);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);

  const layer = document.createElement('canvas');
  function resize() {
    const width = canvas.clientWidth || 1;
    const height = canvas.clientHeight || 1;
    const scale = Math.min(1, 760 / width, 520 / height);
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    makeLightning(layer, canvas.width, canvas.height);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, layer);
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.uniform1f(ratio, width / height);
  }

  resize();
  const start = performance.now();
  let frame = 0;
  let struckAt: number | undefined;
  function render(now: number) {
    const time = (now - start) / 1000;
    if (struckAt === undefined && time >= strikeTime) {
      struckAt = time;
      onStrike();
    }
    if (time >= duration) {
      onEnd();
      return;
    }
    const glow = struckAt === undefined ? 0 : Math.exp(-(time - struckAt) * 8.8);
    gl.uniform1f(elapsed, time);
    gl.uniform1f(pulse, glow);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    frame = requestAnimationFrame(render);
  }
  frame = requestAnimationFrame(render);
  window.addEventListener('resize', resize);
  canvas.addEventListener('webglcontextlost', onEnd);
  return () => {
    cancelAnimationFrame(frame);
    window.removeEventListener('resize', resize);
    canvas.removeEventListener('webglcontextlost', onEnd);
    release();
  };
}
