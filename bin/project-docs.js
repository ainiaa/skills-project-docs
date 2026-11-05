#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

const source = path.resolve(__dirname, "..");
const dependencies = [["brainstorming", "obra/superpowers"], ["grilling", "mattpocock/skills"], ["domain-modeling", "mattpocock/skills"]];
const projectSkills = ["project-docs", "project-docs-api", "project-docs-diagram", "project-docs-lifecycle", "project-docs-overview", "project-docs-product"];
const marker = ".project-docs-managed.json";

// Keep the parent alive long enough to restore backups when the child is interrupted.
process.on("SIGINT", () => { process.exitCode = 130; });
process.on("SIGTERM", () => { process.exitCode = 143; });

function fingerprint(directory) {
  const hash = crypto.createHash("sha256");
  function visit(dir, prefix = "") {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const relative = path.join(prefix, entry.name);
      if (relative === marker) continue;
      const item = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) throw new Error(`拒绝处理包含符号链接的依赖: ${item}`);
      if (entry.name === "__pycache__" && entry.isDirectory()) {
        if (fs.readdirSync(item, { withFileTypes: true }).some(file => !file.isFile() || !file.name.endsWith(".pyc"))) throw new Error(`缓存目录包含用户文件: ${item}`);
        continue;
      }
      hash.update(JSON.stringify([relative, entry.isDirectory() ? "directory" : "file", fs.statSync(item).mode & 0o777]));
      if (entry.isDirectory()) visit(item, relative);
      else if (entry.isFile()) hash.update(fs.readFileSync(item));
      else throw new Error(`不支持的文件类型: ${item}`);
    }
  }
  visit(directory);
  return hash.digest("hex");
}

function main(args) {
  let agent = "codex", global = false, withDeps = false;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--help" || arg === "-h") {
      console.log("Usage: project-docs-skills [--agent codex|claude-code] [--global] [--with-deps]");
      return;
    } else if (arg === "--agent" || arg === "-a") agent = args[++i];
    else if (arg === "--global" || arg === "-g") global = true;
    else if (arg === "--with-deps") withDeps = true;
    else throw new Error(`未知参数: ${arg}`);
  }
  if (!["codex", "claude-code"].includes(agent)) throw new Error("--agent 仅支持 codex 或 claude-code");
  const home = os.homedir();
  const skillRoot = path.join(global ? home : process.cwd(), agent === "codex" ? ".agents/skills" : ".claude/skills");
  // shortcut: serialize this user's installs, use scoped locks if parallel installs become necessary.
  const lockParent = path.join(home, ".agents");
  const installLock = path.join(lockParent, ".project-docs-install.lock");
  fs.mkdirSync(lockParent, { recursive: true });
  try { fs.mkdirSync(installLock); } catch (error) {
    if (error.code === "EEXIST") throw new Error(`已有安装进行中或遗留安装锁，请检查后处理: ${installLock}`);
    throw error;
  }
  try {
  for (const name of projectSkills) {
    const directory = path.join(skillRoot, name);
    if (global && agent === "codex") {
      const hostEntry = path.join(process.env.CODEX_HOME || path.join(home, ".codex"), "skills", name);
      if (fs.lstatSync(hostEntry, { throwIfNoEntry: false }) &&
          !(fs.existsSync(directory) && fs.existsSync(hostEntry) && fs.realpathSync(directory) === fs.realpathSync(hostEntry))) {
        throw new Error(`Codex 已有同名项目 Skill，请先处理: ${hostEntry}`);
      }
    }
    const stat = fs.lstatSync(directory, { throwIfNoEntry: false });
    if (!stat) continue;
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`已有项目 Skill 不是可安全更新的目录: ${directory}`);
    const metadata = fs.lstatSync(path.join(directory, marker), { throwIfNoEntry: false });
    if (metadata) {
      if (!metadata.isFile() || metadata.isSymbolicLink()) throw new Error(`不安全的项目 Skill 元数据: ${directory}`);
      let record;
      try { record = JSON.parse(fs.readFileSync(path.join(directory, marker), "utf8")); } catch { throw new Error(`无效的项目 Skill 元数据: ${directory}`); }
      if (record.source !== "project-docs" || record.fingerprint !== fingerprint(directory)) throw new Error(`已有项目 Skill 已修改或来源不符: ${directory}`);
    } else if (fingerprint(directory) !== fingerprint(path.join(source, "skills", name))) {
      throw new Error(`已有项目 Skill 不是本安装器管理的完整副本: ${directory}`);
    }
  }
  if (withDeps) {
    const hostRoot = agent === "codex"
      ? path.join(process.env.CODEX_HOME || path.join(home, ".codex"), "skills")
      : path.join(process.env.CLAUDE_HOME || path.join(home, ".claude"), "skills");
    const rootsResult = spawnSync("python3", ["-c", "import json,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from install_product_dependencies import visible_roots; print(json.dumps([str(p) for p in visible_roots(Path(sys.argv[2]))]))", path.join(source, "scripts"), hostRoot], { encoding: "utf8" });
    if (rootsResult.error || rootsResult.status !== 0) throw new Error(`无法检查宿主 Skill 路径: ${rootsResult.stderr || rootsResult.error}`);
    const roots = [...new Set([skillRoot, ...JSON.parse(rootsResult.stdout)])];
    for (const [name, repo] of dependencies) {
      const directory = path.join(skillRoot, name);
      for (const root of roots) {
        const candidate = path.join(root, name);
        if (path.resolve(candidate) === path.resolve(directory) || !fs.lstatSync(candidate, { throwIfNoEntry: false })) continue;
        if (fs.existsSync(directory) && fs.existsSync(candidate) && fs.realpathSync(candidate) === fs.realpathSync(directory)) continue;
        throw new Error(`其他宿主路径已有依赖，请先确认其来源: ${candidate}`);
      }
      if (!fs.existsSync(directory) && !fs.lstatSync(directory, { throwIfNoEntry: false })) continue;
      const stat = fs.lstatSync(directory);
      if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`已有依赖不是本安装器管理的目录: ${directory}`);
      let record;
      const metadata = fs.lstatSync(path.join(directory, marker), { throwIfNoEntry: false });
      if (!metadata?.isFile() || metadata.isSymbolicLink()) throw new Error(`已有依赖未由本安装器管理: ${directory}`);
      try { record = JSON.parse(fs.readFileSync(path.join(directory, marker), "utf8")); } catch { throw new Error(`已有依赖未由本安装器管理: ${directory}`); }
      if (record.source !== repo || record.fingerprint !== fingerprint(directory)) throw new Error(`已有依赖已修改或来源不符: ${directory}`);
    }
  }
  function install(repo, name) {
    const options = ["--yes", "skills@latest", "add", repo, "--skill", name, "-a", agent, "--copy", "-y"];
    if (global) options.push("-g");
    const result = spawnSync("npx", options, { stdio: "inherit", timeout: 180000 });
    if (result.error || result.status !== 0) throw new Error(`安装失败: ${repo} (${result.error?.message || result.status})`);
  }
  const lockPath = global ? path.join(home, ".agents/.skill-lock.json") : path.join(process.cwd(), "skills-lock.json");
  function readLock() {
    const stat = fs.lstatSync(lockPath, { throwIfNoEntry: false });
    if (!stat) return null;
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`不安全的 Skill 安装记录: ${lockPath}`);
    const lock = JSON.parse(fs.readFileSync(lockPath, "utf8"));
    if (!lock || typeof lock !== "object" || !lock.skills || typeof lock.skills !== "object" || Array.isArray(lock.skills)) throw new Error(`无效的 Skill 安装记录: ${lockPath}`);
    return lock;
  }
  function restoreLock(before, names) {
    const after = readLock();
    if (!after) {
      if (before) {
        fs.mkdirSync(path.dirname(lockPath), { recursive: true });
        fs.writeFileSync(lockPath, JSON.stringify(before, null, 2) + "\n");
      }
      return;
    }
    for (const name of names) {
      if (before && Object.hasOwn(before.skills, name)) after.skills[name] = before.skills[name];
      else delete after.skills[name];
    }
    fs.writeFileSync(lockPath, JSON.stringify(after, null, 2) + "\n");
  }
  const projectLock = readLock();
  fs.mkdirSync(skillRoot, { recursive: true });
  const projectBackup = fs.mkdtempSync(path.join(skillRoot, ".project-docs-backup-"));
  const moved = [];
  let projectInstallStarted = false;
  try {
    for (const name of projectSkills) {
      const directory = path.join(skillRoot, name);
      if (fs.lstatSync(directory, { throwIfNoEntry: false })) {
        fs.renameSync(directory, path.join(projectBackup, name));
        moved.push(name);
      }
    }
    projectInstallStarted = true;
    install(source, "*");
    for (const name of projectSkills) {
      const directory = path.join(skillRoot, name);
      const installed = fs.lstatSync(directory, { throwIfNoEntry: false });
      if (!installed?.isDirectory() || installed.isSymbolicLink() || !fs.existsSync(path.join(directory, "SKILL.md"))) throw new Error(`不安全或不完整的项目 Skill 安装目录: ${directory}`);
      const metadata = fs.lstatSync(path.join(directory, marker), { throwIfNoEntry: false });
      if (metadata && (!metadata.isFile() || metadata.isSymbolicLink())) throw new Error(`不安全的项目 Skill 元数据: ${directory}`);
      const installedFingerprint = fingerprint(directory);
      if (installedFingerprint !== fingerprint(path.join(source, "skills", name))) throw new Error(`项目 Skill 安装不完整或内容不一致: ${directory}`);
      fs.writeFileSync(path.join(directory, marker), JSON.stringify({ source: "project-docs", fingerprint: installedFingerprint }) + "\n");
    }
  } catch (error) {
    try {
      if (projectInstallStarted) for (const name of projectSkills) fs.rmSync(path.join(skillRoot, name), { recursive: true, force: true });
      for (const name of moved) fs.renameSync(path.join(projectBackup, name), path.join(skillRoot, name));
      if (projectInstallStarted) restoreLock(projectLock, projectSkills);
      fs.rmSync(projectBackup, { recursive: true, force: true });
    } catch (restoreError) {
      throw new Error(`${error.message}; 恢复失败: ${restoreError.message}; 原项目 Skill 备份: ${projectBackup}`);
    }
    throw error;
  }
  fs.rmSync(projectBackup, { recursive: true, force: true });
  if (withDeps) for (const [name, repo] of dependencies) {
    const directory = path.join(skillRoot, name);
    const dependencyLock = readLock();
    fs.mkdirSync(skillRoot, { recursive: true });
    const backup = fs.mkdtempSync(path.join(skillRoot, ".project-docs-backup-"));
    const previous = path.join(backup, "previous");
    const hadPrevious = !!fs.lstatSync(directory, { throwIfNoEntry: false });
    if (hadPrevious) fs.renameSync(directory, previous);
    try {
      install(repo, name);
      const installed = fs.lstatSync(directory, { throwIfNoEntry: false });
      if (!installed?.isDirectory() || installed.isSymbolicLink()) throw new Error(`不安全的依赖安装目录: ${directory}`);
      if (!fs.existsSync(path.join(directory, "SKILL.md"))) throw new Error(`安装后缺少 ${directory}/SKILL.md`);
      const validation = spawnSync("python3", ["-c", "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from product_dependencies import REQUIRED,inspect_skill; r=inspect_skill(Path(sys.argv[2]),sys.argv[3],REQUIRED[sys.argv[3]]); print('; '.join(r['problems'])); sys.exit(bool(r['problems']))", path.join(source, "scripts"), directory, name], { encoding: "utf8" });
      if (validation.error || validation.status !== 0) throw new Error(`依赖校验失败 ${name}: ${validation.stdout || validation.stderr || validation.error}`);
      const metadata = fs.lstatSync(path.join(directory, marker), { throwIfNoEntry: false });
      if (metadata && (!metadata.isFile() || metadata.isSymbolicLink())) throw new Error(`不安全的依赖元数据: ${directory}`);
      fs.writeFileSync(path.join(directory, marker), JSON.stringify({ source: repo, fingerprint: fingerprint(directory) }) + "\n");
    } catch (error) {
      try {
        fs.rmSync(directory, { recursive: true, force: true });
        if (hadPrevious) fs.renameSync(previous, directory);
        restoreLock(dependencyLock, [name]);
      } catch (restoreError) {
        throw new Error(`${error.message}; 恢复失败: ${restoreError.message}; 原依赖备份: ${previous}`);
      }
      throw error;
    } finally {
      if (!fs.lstatSync(previous, { throwIfNoEntry: false })) fs.rmSync(backup, { recursive: true, force: true });
    }
    fs.rmSync(backup, { recursive: true, force: true });
  }
  } finally {
    fs.rmdirSync(installLock);
  }
}

try { main(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exitCode = 1; }
