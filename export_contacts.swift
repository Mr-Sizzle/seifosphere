#!/usr/bin/env swift
// export_contacts.swift
// Exports all contacts with phone numbers as "digits|First Last" lines to stdout.
// Used by server.py to build the contact map.

import Contacts
import Foundation

let store = CNContactStore()
let keys: [CNKeyDescriptor] = [
    CNContactGivenNameKey as CNKeyDescriptor,
    CNContactFamilyNameKey as CNKeyDescriptor,
    CNContactPhoneNumbersKey as CNKeyDescriptor,
    CNContactNicknameKey as CNKeyDescriptor,
]

var lines: [String] = []

do {
    let request = CNContactFetchRequest(keysToFetch: keys)
    try store.enumerateContacts(with: request) { contact, _ in
        let parts = [contact.givenName, contact.familyName].filter { !$0.isEmpty }
        let name: String
        if parts.isEmpty {
            name = contact.nickname.isEmpty ? "" : contact.nickname
        } else {
            name = parts.joined(separator: " ")
        }
        guard !name.isEmpty else { return }
        for ph in contact.phoneNumbers {
            let raw = ph.value.stringValue
            let digits = raw.filter { $0.isNumber }
            guard digits.count >= 10 else { continue }
            lines.append("\(digits)|\(name)")
            // Also store last-10 variant for US numbers
            if digits.count > 10 {
                let last10 = String(digits.suffix(10))
                lines.append("\(last10)|\(name)")
            }
        }
    }
} catch {
    fputs("error: \(error)\n", stderr)
    exit(1)
}

print(lines.joined(separator: "\n"))
