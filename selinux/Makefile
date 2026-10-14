# 构建 openclaw_agent SELinux 模块（使用发行版提供的策略开发头文件）
AWK ?= gawk
NAME := openclaw_agent

all: $(NAME).pp

$(NAME).pp: $(NAME).te $(NAME).fc $(NAME).if
	make -f /usr/share/selinux/devel/Makefile $(NAME).pp

load: all
	semodule -i $(NAME).pp

reload: all
	semodule -i $(NAME).pp && restorecon -RvF \
		/usr/lib/node_modules/openclaw \
		/usr/local/bin/openclaw-tool-e2e \
		/usr/local/bin/openclaw-selinux-file-search-read \
		/usr/local/libexec/openclaw-round-id-listener.py \
		/usr/local/libexec/run-openclaw-tracee-collector-service \
		/usr/local/libexec/openclaw-selinux \
		/home/hx/jjq/agent_perm_audit/tools \
		/root/.openclaw/skills \
		/var/lib/openclaw-kernel-collector

unload:
	semodule -r $(NAME) || true

clean:
	rm -f $(NAME).pp $(NAME).mod tmp/ -r
