"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MEMBERSHIP_ROLES } from "@/constants/admin";
import {
  AdminRequestError,
  createInvitation,
  getInvitations,
  getMembers,
  revokeInvitation,
  updateMember,
} from "@/lib/api/admin";
import type {
  OrganizationInvitation,
  OrganizationMember,
} from "@/types/admin";
import type { MembershipRole } from "@/types/auth";

const readableRole = (role: MembershipRole) =>
  role === "AP_MANAGER"
    ? "AP manager"
    : role === "ORG_ADMIN"
      ? "Organization admin"
      : "Member";
const dateTime = (value: string) => new Date(value).toLocaleString();

export function MembersPage() {
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [memberCursor, setMemberCursor] = useState<string | null>(null);
  const [inviteCursor, setInviteCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const feedback = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setConflict(false);
    try {
      const [memberPage, invitationPage] = await Promise.all([
        getMembers(),
        getInvitations(),
      ]);
      setMembers(memberPage.items);
      setInvitations(invitationPage.items);
      setMemberCursor(memberPage.next_cursor);
      setInviteCursor(invitationPage.next_cursor);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Administration could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const pending = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(pending);
  }, [refresh]);
  useEffect(() => {
    if (error) feedback.current?.focus();
  }, [error]);

  function failed(caught: unknown) {
    setConflict(caught instanceof AdminRequestError && caught.status === 409);
    setError(
      caught instanceof Error ? caught.message : "The change could not be saved.",
    );
  }

  async function changeMember(
    member: OrganizationMember,
    changes: { role?: MembershipRole; status?: "ACTIVE" | "ARCHIVED" },
  ) {
    if (busy) return;
    setBusy(member.user_id);
    setError(null);
    setConflict(false);
    try {
      const updated = await updateMember(member, changes);
      setMembers((current) =>
        current.map((item) =>
          item.user_id === member.user_id ? { ...item, ...updated } : item,
        ),
      );
    } catch (caught) {
      failed(caught);
    } finally {
      setBusy(null);
    }
  }

  async function submitInvitation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy("invitation-form");
    setError(null);
    setConflict(false);
    try {
      const created = await createInvitation(
        String(data.get("email") ?? ""),
        String(data.get("role") ?? "MEMBER") as MembershipRole,
      );
      setInvitations((current) => [created, ...current]);
      form.reset();
    } catch (caught) {
      failed(caught);
    } finally {
      setBusy(null);
    }
  }

  async function revoke(value: OrganizationInvitation) {
    if (busy) return;
    setBusy(value.id);
    setError(null);
    setConflict(false);
    try {
      const changed = await revokeInvitation(value);
      setInvitations((current) =>
        current.map((item) => (item.id === value.id ? changed : item)),
      );
    } catch (caught) {
      failed(caught);
    } finally {
      setBusy(null);
    }
  }

  async function moreMembers() {
    if (!memberCursor || busy) return;
    setBusy("members-more");
    try {
      const page = await getMembers(memberCursor);
      setMembers((current) => [...current, ...page.items]);
      setMemberCursor(page.next_cursor);
    } catch (caught) {
      failed(caught);
    } finally {
      setBusy(null);
    }
  }

  async function moreInvitations() {
    if (!inviteCursor || busy) return;
    setBusy("invitations-more");
    try {
      const page = await getInvitations(inviteCursor);
      setInvitations((current) => [...current, ...page.items]);
      setInviteCursor(page.next_cursor);
    } catch (caught) {
      failed(caught);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-10">
      <section className="space-y-5" aria-labelledby="members-title">
        <div>
          <h1 id="members-title" className="text-2xl font-semibold">
            Members
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Roles and access status apply only to this organization. Accounts,
            credentials, and other memberships are not changed here.
          </p>
        </div>
        {error && (
          <div
            ref={feedback}
            tabIndex={-1}
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-destructive/40 p-3 text-sm text-destructive"
          >
            <span>{error}</span>
            {conflict && (
              <Button type="button" variant="outline" onClick={() => void refresh()}>
                Refresh
              </Button>
            )}
          </div>
        )}
        {loading ? (
          <p role="status">Loading organization members…</p>
        ) : (
          <>
            <Table aria-label="Organization members" scrollLabel="Member table scroll area">
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Member</TableHead>
                  <TableHead scope="col">Email</TableHead>
                  <TableHead scope="col">Role</TableHead>
                  <TableHead scope="col">Status</TableHead>
                  <TableHead scope="col">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((member) => (
                  <TableRow key={member.user_id}>
                    <TableHead scope="row" className="max-w-56 whitespace-normal break-words">
                      {member.display_name}
                    </TableHead>
                    <TableCell className="max-w-64 whitespace-normal break-all">
                      {member.email}
                    </TableCell>
                    <TableCell>
                      <Label className="sr-only" htmlFor={`role-${member.user_id}`}>
                        Role for {member.display_name}
                      </Label>
                      <select
                        id={`role-${member.user_id}`}
                        className="rounded-md border bg-background p-2"
                        value={member.role}
                        disabled={busy === member.user_id}
                        onChange={(event) =>
                          void changeMember(member, {
                            role: event.target.value as MembershipRole,
                          })
                        }
                      >
                        {MEMBERSHIP_ROLES.map((role) => (
                          <option key={role} value={role}>
                            {readableRole(role)}
                          </option>
                        ))}
                      </select>
                    </TableCell>
                    <TableCell>{member.status === "ACTIVE" ? "Active" : "Inactive"}</TableCell>
                    <TableCell>
                      <Button
                        type="button"
                        variant={member.status === "ACTIVE" ? "destructive" : "outline"}
                        disabled={busy === member.user_id}
                        onClick={() =>
                          void changeMember(member, {
                            status: member.status === "ACTIVE" ? "ARCHIVED" : "ACTIVE",
                          })
                        }
                      >
                        {member.status === "ACTIVE" ? "Deactivate" : "Reactivate"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {memberCursor && (
              <Button variant="outline" onClick={() => void moreMembers()} disabled={!!busy}>
                Load more members
              </Button>
            )}
          </>
        )}
      </section>

      <section className="space-y-5" aria-labelledby="invitations-title">
        <div>
          <h2 id="invitations-title" className="text-xl font-semibold">
            Invitations
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Pending invitations expire automatically. Revoke one before
            issuing another invitation to the same address.
          </p>
        </div>
        <form
          onSubmit={submitInvitation}
          className="grid items-end gap-4 rounded-lg border bg-card p-4 md:grid-cols-[minmax(0,1fr)_12rem_auto]"
        >
          <div className="space-y-2">
            <Label htmlFor="invitation-email">Email</Label>
            <Input
              id="invitation-email"
              name="email"
              type="email"
              autoComplete="email"
              maxLength={254}
              required
              disabled={busy === "invitation-form"}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="invitation-role">Role</Label>
            <select
              id="invitation-role"
              name="role"
              className="h-8 w-full rounded-md border bg-background px-2 text-sm"
              defaultValue="MEMBER"
              disabled={busy === "invitation-form"}
            >
              {MEMBERSHIP_ROLES.map((role) => (
                <option key={role} value={role}>
                  {readableRole(role)}
                </option>
              ))}
            </select>
          </div>
          <Button type="submit" disabled={busy === "invitation-form"}>
            {busy === "invitation-form" ? "Sending…" : "Send invitation"}
          </Button>
        </form>
        {!loading && !invitations.length ? (
          <p className="text-sm text-muted-foreground">No invitations yet.</p>
        ) : (
          <Table aria-label="Organization invitations" scrollLabel="Invitation table scroll area">
            <TableHeader>
              <TableRow>
                <TableHead scope="col">Email</TableHead>
                <TableHead scope="col">Role</TableHead>
                <TableHead scope="col">Created</TableHead>
                <TableHead scope="col">Expires</TableHead>
                <TableHead scope="col">State</TableHead>
                <TableHead scope="col">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invitations.map((invitation) => (
                <TableRow key={invitation.id}>
                  <TableHead scope="row" className="max-w-64 whitespace-normal break-all">
                    {invitation.email}
                  </TableHead>
                  <TableCell>{readableRole(invitation.role)}</TableCell>
                  <TableCell>{dateTime(invitation.created_at)}</TableCell>
                  <TableCell>{dateTime(invitation.expires_at)}</TableCell>
                  <TableCell>
                    {invitation.expired ? "Expired" : invitation.status.toLowerCase()}
                  </TableCell>
                  <TableCell>
                    {invitation.status === "PENDING" && (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={busy === invitation.id}
                        onClick={() => void revoke(invitation)}
                      >
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {inviteCursor && (
          <Button variant="outline" onClick={() => void moreInvitations()} disabled={!!busy}>
            Load more invitations
          </Button>
        )}
      </section>
    </div>
  );
}
