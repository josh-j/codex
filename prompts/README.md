# prompts/

Reusable, agent-agnostic prompts for recurring authoring and refactoring tasks
in this repo. Each file is a self-contained instruction set meant to be pasted
into any coding agent (or referenced by path) so it can execute without relying
on conversation history or tool-specific features.

## Index

- [`stig_from_xccdf.md`](stig_from_xccdf.md) — given a DISA XCCDF benchmark,
  scaffold a ground-up `stig_<version>/` task folder that matches the
  conventions used by the existing STIGs under
  `ncs-ansible-<platform>/roles/<sub_platform>/tasks/stig_*/`.
