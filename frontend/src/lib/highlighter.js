// Prism *light* build with the languages people actually paste. The full
// build registers ~300 grammars (223 kB gzip); this keeps code blocks
// highlighted at a fraction of the download. Unknown languages render plain.
import { PrismLight } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import csharp from "react-syntax-highlighter/dist/esm/languages/prism/csharp";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff";
import docker from "react-syntax-highlighter/dist/esm/languages/prism/docker";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import kotlin from "react-syntax-highlighter/dist/esm/languages/prism/kotlin";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import php from "react-syntax-highlighter/dist/esm/languages/prism/php";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import ruby from "react-syntax-highlighter/dist/esm/languages/prism/ruby";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import swift from "react-syntax-highlighter/dist/esm/languages/prism/swift";
import toml from "react-syntax-highlighter/dist/esm/languages/prism/toml";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";

const LANGS = { bash, c, cpp, csharp, css, diff, docker, go, java, javascript, json, jsx, kotlin, markdown, markup, php, python, ruby, rust, sql, swift, toml, tsx, typescript, yaml };
for (const [name, grammar] of Object.entries(LANGS)) PrismLight.registerLanguage(name, grammar);
// Common aliases models emit.
const ALIASES = { js: javascript, ts: typescript, py: python, sh: bash, shell: bash, zsh: bash, html: markup, xml: markup, yml: yaml, md: markdown, "c++": cpp, cs: csharp, dockerfile: docker, rs: rust, golang: go };
for (const [name, grammar] of Object.entries(ALIASES)) PrismLight.registerLanguage(name, grammar);

export default PrismLight;
