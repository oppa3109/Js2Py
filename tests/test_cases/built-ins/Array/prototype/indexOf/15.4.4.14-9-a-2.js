// Copyright (c) 2012 Ecma International.  All rights reserved.
// Ecma International makes this code available under the terms and conditions set
// forth on http://hg.ecmascript.org/tests/test262/raw-file/tip/LICENSE (the
// "Use Terms").   Any redistribution of this code must retain the above
// copyright and this notice and otherwise comply with the Use Terms.

/*---
es5id: 15.4.4.14-9-a-2
description: >
    Array.prototype.indexOf - added properties in step 5 are visible
    here on an Array-like object
includes: [runTestCase.js]
---*/

function testcase() {

        var arr = { length: 30 };
        var targetObj = function () { };

        var fromIndex = {
            valueOf: function () {
                arr[4] = targetObj;
                return 3;
            }
        };
        
        return 4 === Array.prototype.indexOf.call(arr, targetObj, fromIndex);
    }
runTestCase(testcase);
